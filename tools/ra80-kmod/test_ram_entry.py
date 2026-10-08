#!/usr/bin/env python3
"""Exercise the actual RAM entry function with fake environment/network calls."""
import os
import re
import subprocess
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[2]
source = (root/'common/main.c').read_text()
begin = source.index('static void ra80_ram_network_loop(')
body = source.index('{', begin)
depth, end = 1, body+1
while depth:
    depth += (source[end] == '{') - (source[end] == '}')
    end += 1
function = source[begin:end]
header = (root/'include/ra80_bootstage.h').read_text()
defines = '\n'.join(line for line in header.splitlines() if re.match(r'#define RA80_(?:NET|STAGE)_', line))
prefix = r'''
#include <assert.h>
#include <setjmp.h>
#include <string.h>
#include <stdio.h>
#define RA80_RAMBOOT_MAGIC_GUARD 0x5241382fU
#define GD_FLG_DISABLE_CONSOLE 0x40U
static struct { unsigned flags; } gd_data, *gd=&gd_data;
static unsigned ra80_ramboot_magic;
static int webfailsafe_is_running,net_httpd_ip,net_ip;
static int devices_result,http_ok,fail_env,env_calls,eth_calls,http_calls,poll_calls;
static jmp_buf escape;
static void hang(void) { longjmp(escape,2); }
static void ra80_net_stage(unsigned ordinal,unsigned code) { (void)ordinal; (void)code; }
static void ra80_bootstage(unsigned code) { (void)code; }
static int fake_setenv(const char *name,const char *value) {
    assert(gd->flags & GD_FLG_DISABLE_CONSOLE);
    assert(ra80_ramboot_magic==RA80_RAMBOOT_MAGIC_GUARD);
    env_calls++;
    if(!strcmp(name,"ethact") || !strcmp(name,"ethprime")) assert(value==NULL);
    return fail_env && !strcmp(name,"ethrotate") ? 1 : 0;
}
#define setenv fake_setenv
static int eth_initialize(void) { assert(env_calls==5); eth_calls++; return devices_result; }
static void HttpdStart(void) { assert(eth_calls==1); http_calls++; webfailsafe_is_running=http_ok; net_ip=123; }
static void net_copy_ip(int *to,int *from) { *to=*from; }
static void httpd_poll(void) {
    assert(http_calls==1 && webfailsafe_is_running && net_httpd_ip==net_ip);
    if(++poll_calls==2) longjmp(escape,1);
}
'''
tests = r'''
static int attempt(int devices,int http,int env_fail) {
    gd_data.flags=0; ra80_ramboot_magic=0x52413830U;
    webfailsafe_is_running=0; env_calls=eth_calls=http_calls=poll_calls=0;
    devices_result=devices;http_ok=http;fail_env=env_fail;
    int result=setjmp(escape);
    if(!result) { ra80_ram_network_loop(); assert(0); }
    return result;
}
int main(void) {
    assert(attempt(2,1,0)==1 && eth_calls==1 && http_calls==1 && poll_calls==2);
    assert(attempt(0,1,0)==2 && eth_calls==1 && http_calls==0 && poll_calls==0);
    assert(attempt(2,1,1)==2 && eth_calls==0 && http_calls==0 && poll_calls==0);
    assert(attempt(2,0,0)==2 && eth_calls==1 && http_calls==1 && poll_calls==0);
    puts("PASS: actual RAM entry disables console, registers once and polls directly; env/no-device/HTTP failures stop safely");
}
'''
with tempfile.TemporaryDirectory(prefix='ra80-entry-test-') as tmp:
    path = Path(tmp)/'test.c'
    exe = Path(tmp)/('test.exe' if os.name=='nt' else 'test')
    path.write_text(prefix + defines + '\n' + function + tests)
    subprocess.run([os.environ.get('CC','cc'),'-std=c99',str(path),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
