#!/usr/bin/env python3
"""Exercise actual binary-upload parsing, FIT validation and response ACK ownership."""
import os, subprocess, tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[2]

def function(path, signature):
 s=(root/path).read_text();a=s.index(signature);b=s.index('{',a)+1;d=1
 while d:d+=(s[b]=='{')-(s[b]=='}');b+=1
 return s[a:b]

prefix=r'''
#include <assert.h>
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <libfdt.h>
typedef unsigned long ulong;
typedef uint64_t u64;
typedef unsigned char u8_t;
typedef uint32_t u32_t;
#include "ra80_ram_upload.h"
#define CONFIG_SYS_BOOTM_LEN 0x4000000UL
#define RAM_BOOT_ADDR 0x44000000UL
static unsigned char memory[65536];
#define UPLOAD_ADDR ((ulong)memory)
#define RA80_RAM_UPLOAD_ADDR UPLOAD_ADDR
#define CONFIG_SYS_SDRAM_END ((u64)UPLOAD_ADDR + sizeof(memory))
#define STATE_NONE 0
#define STATE_FILE_REQUEST 1
#define TCP_PRIO_MIN 1
struct failsafe_httpd_state { int state; unsigned long last_activity; u8_t *dataptr; ulong upload,upload_total; int owns_global; unsigned ram_reply_pending; void *pcb; };
static struct { int done,failed,ram_raw,packet_counter; } upload;
static struct ra80_ram_upload ram_upload;
static struct { u32_t received,total,updated,log_mark; } ram_progress;
static int upgrade_status;
static struct { int unused; } backup;
static struct failsafe_httpd_state *hs_global;
static char *boundary_value;
static void *flashread_yield_fn;
static unsigned char *webfailsafe_data_pointer;
static ulong net_boot_file_size;
static int webfailsafe_ready_for_upgrade, replies;
static const char *last_response;
static unsigned long get_timer(int x){return 0;}
static void tcp_setprio(void *pcb,int priority){}
static void led_on(const char *name){}
static void httpd_send_data(struct failsafe_httpd_state *hs){
 assert(!webfailsafe_ready_for_upgrade);replies++;last_response=(const char *)hs->dataptr;hs->upload=0;
}
'''
source='\n'.join(function('failsafe/failsafe_httpd.c',sig) for sig in [
 'static void httpd_state_reset(', 'static void httpd_ram_upload_reply(',
 'static int httpd_ram_reply_acked(', 'static void httpd_handle_ram_upload('])
tests=r'''
static void begin(struct failsafe_httpd_state *hs){
 memset(hs,0,sizeof(*hs));memset(&upload,0,sizeof(upload));memset(&ram_upload,0,sizeof(ram_upload));
 memset(&ram_progress,0,sizeof(ram_progress));upgrade_status=7;
 memset(memory,0xa5,sizeof(memory));hs->owns_global=1;hs_global=hs;upload.ram_raw=1;
 webfailsafe_data_pointer=memory;net_boot_file_size=0;webfailsafe_ready_for_upgrade=0;replies=0;
}
static size_t make_wire(char *wire,unsigned char *fit){
 assert(!fdt_create_empty_tree(fit,4096));assert(fdt_add_subnode(fit,0,"images")>=0);
 assert(fdt_add_subnode(fit,0,"configurations")>=0);assert(!fdt_pack(fit));
 unsigned size=fdt_totalsize(fit);
 int header=sprintf(wire,"POST /ramboot HTTP/1.1\r\nHost: 192.168.1.1\r\nContent-Length: %u\r\nContent-Type: application/octet-stream\r\n\r\n",size);
 memcpy(wire+header,fit,size);return header+size;
}
static int parse_request(const char *wire,unsigned long limit){
 struct ra80_ram_upload s={0};ulong off,count;
 return ra80_ram_upload_feed(&s,wire,strlen(wire),limit,&off,&count);
}
int main(void){
 char wire[8192];unsigned char fit[4096];size_t total=make_wire(wire,fit);unsigned fit_size=fdt_totalsize(fit);
 struct failsafe_httpd_state hs,other={0};
 /* Every possible two-packet split, including inside every header field. */
 for(size_t cut=1;cut<total;cut++){
  begin(&hs);httpd_handle_ram_upload(&hs,wire,cut);assert(!replies && !webfailsafe_ready_for_upgrade);
  httpd_handle_ram_upload(&hs,wire+cut,total-cut);
  assert(replies==1 && strstr(last_response,"200 OK") && net_boot_file_size==fit_size);
  assert(!memcmp(memory,fit,fit_size) && webfailsafe_data_pointer==memory+fit_size);
  assert(memory[fit_size]==0xa5 && !upload.done && hs.owns_global && hs_global==&hs);
  assert(upgrade_status==1 && ram_progress.received==fit_size && ram_progress.total==fit_size);
  assert(!httpd_ram_reply_acked(&other,5000) && !webfailsafe_ready_for_upgrade);
  unsigned pending=hs.ram_reply_pending;assert(pending>1);
  assert(httpd_ram_reply_acked(&hs,1)==1 && hs.ram_reply_pending==pending-1 && !webfailsafe_ready_for_upgrade);
  assert(!httpd_ram_reply_acked(&hs,pending-1) && webfailsafe_ready_for_upgrade);
  httpd_state_reset(&hs);assert(!hs_global && !hs.owns_global);
 }
 begin(&hs);for(size_t i=0;i<total;i++)httpd_handle_ram_upload(&hs,wire+i,1);
 assert(replies==1 && !memcmp(memory,fit,fit_size));
 begin(&hs);httpd_handle_ram_upload(&hs,wire,total-1);assert(!replies && !net_boot_file_size);
 httpd_state_reset(&hs);assert(!hs_global && !webfailsafe_ready_for_upgrade);
 assert(upgrade_status==9 && ram_progress.received==fit_size-1 && ram_progress.total==fit_size);
 begin(&hs);httpd_handle_ram_upload(&hs,wire,total);httpd_state_reset(&hs);
 assert(!httpd_ram_reply_acked(&hs,5000) && !webfailsafe_ready_for_upgrade);
 puts("PASS: actual RAM handler accepts every header/body split and bytewise input, copies only exact FIT bytes, cancels truncation/disconnect, and arms only after the owner response is fully ACKed");

 begin(&hs);wire[total]=0;httpd_handle_ram_upload(&hs,wire,total+1);
 assert(replies==1 && strstr(last_response,"400 Bad Request") && !net_boot_file_size && memory[0]==0xa5);
 total=make_wire(wire,fit);char *body=strstr(wire,"\r\n\r\n")+4;
 ((struct fdt_header *)fit)->totalsize=cpu_to_fdt32(fit_size+4);memcpy(body,fit,fit_size);
 begin(&hs);httpd_handle_ram_upload(&hs,wire,total);
 assert(strstr(last_response,"422 Unprocessable") && !hs.owns_global && !hs.ram_reply_pending && !webfailsafe_ready_for_upgrade);
 assert(upgrade_status==8 && ram_progress.received==fit_size);
 begin(&hs);const char *big="POST /ramboot HTTP/1.1\r\nContent-Type: application/octet-stream\r\nContent-Length: 65537\r\n\r\n";
 httpd_handle_ram_upload(&hs,big,strlen(big));assert(strstr(last_response,"413 Payload") && memory[0]==0xa5);
 const char *bad[]={
  "POST / HTTP/1.1\r\nContent-Type: application/octet-stream\r\nContent-Length: 40\r\n\r\n",
  "POST /ramboot HTTP/1.1\r\nContent-Type: application/octet-stream\r\n\r\n",
  "POST /ramboot HTTP/1.1\r\nContent-Type: application/octet-stream\r\nContent-Length: -1\r\n\r\n",
  "POST /ramboot HTTP/1.1\r\nContent-Type: application/octet-stream\r\nContent-Length: 40\r\nContent-Length: 40\r\n\r\n",
  "POST /ramboot HTTP/1.1\r\nContent-Type: application/octet-stream\r\nContent-Length: 40\r\nTransfer-Encoding: chunked\r\n\r\n",
  "POST /ramboot HTTP/1.1\r\nContent-Type: multipart/form-data\r\nContent-Length: 40\r\n\r\n",
  "POST /ramboot HTTP/1.1\r\nContent-Type: application/octet-stream\r\nContent-Length: 39\r\n\r\n",
  "POST /ramboot HTTP/1.1\r\nContent-Type: application/octet-stream\r\nContent-Length: 999999999999999999999999999999\r\n\r\n"};
 for(unsigned i=0;i<sizeof(bad)/sizeof(bad[0]);i++)assert(parse_request(bad[i],0x4000000)<0);
 assert(parse_request("POST /ramboot HTTP/1.1\r\ncontent-type: application/octet-stream\r\ncontent-length: 13944692\r\n\r\n",0x4000000)==RA80_UPLOAD_MORE);
 char huge[3000];memset(huge,'x',sizeof(huge));memcpy(huge,"POST /ramboot HTTP/1.1\r\nX: ",25);huge[2999]=0;
 assert(parse_request(huge,0x4000000)<0);
 puts("PASS: actual RAM upload rejects extra bytes, FIT length mismatch, oversize, duplicate/missing/overflowed length, chunked/multipart and oversized headers without arming boot");
}
'''
js=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
let multipart=0,posted=[],failure='',polled=0,failUpload=false,ram=true;
const file={size:13944692},input={name:'initramfs',files:[file]},button={};
const form={querySelector:s=>s==='input[type=file]'?input:button};
const card={innerHTML:'',querySelector:()=>({set textContent(s){failure=s;}})};
const document={querySelector:s=>s==='.card'?card:{addEventListener(){}},getElementById:()=>null};
const context={document,window:{addEventListener(){}},location:{hash:''},
 FormData:function(f){multipart++;this.form=f;},localStorage:{getItem:()=>null},
 showStep(){},setTimeout(){},fetch:async(url,options)=>{
  if(url==='/about')return {ok:true,json:async()=>({ram_only:ram})};
  posted.push({url,options});return {ok:!failUpload,status:413,text:async()=>'<actual server rejection>'};
 }};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),context);
context.pollUpgradeStatus=()=>polled++;
(async()=>{
 context.handleSubmit({preventDefault(){},target:form});await new Promise(r=>setImmediate(r));
 assert.equal(posted.length,1);assert.equal(posted[0].url,'/ramboot');assert.strictEqual(posted[0].options.body,file);
 assert.equal(posted[0].options.headers['Content-Type'],'application/octet-stream');assert.equal(multipart,0);assert.equal(polled,1);
 posted=[];input.name='uboot';context.handleSubmit({preventDefault(){},target:form});await new Promise(r=>setImmediate(r));
 assert.equal(posted.length,0);assert(failure.includes('RAM'));
 input.name='initramfs';failUpload=true;failure='';context.handleSubmit({preventDefault(){},target:form});await new Promise(r=>setImmediate(r));
 assert.equal(failure,'<actual server rejection>');assert.equal(polled,1);assert(!card.innerHTML.includes('<actual'));
 ram=false;failUpload=false;posted=[];context.handleSubmit({preventDefault(){},target:form});await new Promise(r=>setImmediate(r));
 assert.equal(posted[0].url,'/');assert.equal(multipart,1);
 console.log('PASS: actual browser submission uses a single binary File in RAM mode, blocks flash selections, preserves normal multipart and renders server errors as text');
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
console_prefix=r'''
#include <assert.h>
#include <stdio.h>
#define CONFIG_DISABLE_CONSOLE 1
#define CONFIG_LWIP_HTTPD 1
#define CONFIG_IPQ5018_XIAOMI_RA80 1
#define GD_FLG_DISABLE_CONSOLE 64
#define GD_FLG_DEVINIT 2
static struct { unsigned flags; int have_console; } gd_data,*gd=&gd_data;
static int ram,web,uart;
static int ra80_ram_test_active(void){return ram;}
static void webterm_putc(char c){web++;}
static void webterm_capture_output(const char *s){web++;}
static void pre_console_putc(char c){uart++;}
static void pre_console_puts(const char *s){uart++;}
static void serial_putc(char c){uart++;}
static void serial_puts(const char *s){uart++;}
static void fake_fputc(int fd,char c){uart++;}
static void fake_fputs(int fd,const char *s){uart++;}
#undef stdout
#define stdout 1
#define fputc fake_fputc
#define fputs fake_fputs
#define putc test_putc
#define puts test_puts
'''
console_code='\n'.join(function('common/console.c',sig) for sig in ['void putc(const char c)','void puts(const char *s)'])
console_tests=r'''
int main(void){
 gd->flags=GD_FLG_DISABLE_CONSOLE;gd->have_console=1;ram=1;
 test_putc('x');test_puts("message");assert(web==2 && !uart);
 ram=0;web=0;test_putc('x');test_puts("message");assert(!web && !uart);
 gd->flags=0;test_putc('x');test_puts("message");assert(web==2 && uart>0);
}
'''
with tempfile.TemporaryDirectory(prefix='ra80-upload-') as tmp:
 tmp=Path(tmp);src=tmp/'test.c';exe=tmp/'test';src.write_text(prefix+source+tests)
 subprocess.run([os.environ.get('CC','cc'),'-std=c99','-Wall','-I',str(root/'failsafe'),str(src),'-o',str(exe),'-lfdt'],check=True)
 result=subprocess.run([str(exe)],check=True,stdout=subprocess.PIPE,text=True)
 print('\n'.join(line for line in result.stdout.splitlines() if line.startswith('PASS:')))
 console_src=tmp/'console.c';console_exe=tmp/'console';console_src.write_text(console_prefix+console_code+console_tests)
 subprocess.run([os.environ.get('CC','cc'),'-std=c99','-Wall',str(console_src),'-o',str(console_exe)],check=True)
 subprocess.run([str(console_exe)],check=True)
 print('PASS: actual console retains Web diagnostics in RAM mode, calls no UART/stdio helpers, and preserves normal console behavior')
 script=tmp/'test.js';script.write_text(js)
 subprocess.run(['node',str(script),str(root/'failsafe/html/pig/submit.js')],check=True)
