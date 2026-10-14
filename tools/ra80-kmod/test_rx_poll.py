#!/usr/bin/env python3
"""Test production PHY monitoring with bounded fake MDIO, no hardware access."""
import os, re, subprocess, tempfile
from pathlib import Path
root = Path(__file__).resolve().parents[2]
source = (root/'lib/ipq_api.c').read_text()

def function(signature):
    start = source.index(signature)
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]

interval = source[source.index('#ifdef CONFIG_IPQ5018_XIAOMI_RA80\n#define LINK_CHECK_INTERVAL'):source.index('#define PHY_SPEC_STATUS')]
prefix = r'''
#include <assert.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>
typedef unsigned long ulong;
typedef unsigned short ushort;
#define PHY_MAX_ADDR 32
#define PHY_SPEC_STATUS 17
#define PHY_LINK_PASS 0x400
#define MII_BMSR 1
#define BMSR_LSTATUS 4
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
static ulong clock_ms, link_last_check;
static int link_first_check,link_port_prev,mdio_calls,init_calls;
static int live_bus=-1,live_phy=-1,read_error,latched_low;
static ulong get_timer(ulong base){return clock_ms-base;}
static const char *miiphy_get_current_dev(void){return "IPQ MDIO1";}
static int eth_init(void){init_calls++;return 0;}
static int miiphy_read(const char *dev,int phy,int reg,ushort *value){
    int bus=!strcmp(dev,"IPQ MDIO0")?0:1;
    assert(!strcmp(dev,"IPQ MDIO0") || !strcmp(dev,"IPQ MDIO1"));
#ifdef CONFIG_IPQ5018_XIAOMI_RA80
    assert((bus==0 && phy==7) || (bus==1 && phy>=0 && phy<5));
#endif
    mdio_calls++;
    if(read_error)return -1;
    *value=0xffff;
    if(bus==live_bus && phy==live_phy){
        if(reg==PHY_SPEC_STATUS)*value=latched_low?0:PHY_LINK_PASS;
        else if(reg==MII_BMSR){*value=latched_low==1?0:BMSR_LSTATUS;latched_low=2;}
    }
    return 0;
}
static void tick(void){clock_ms+=LINK_CHECK_INTERVAL;}
'''
tests = r'''
int main(void){
    clock_ms=LINK_CHECK_INTERVAL-1;
    assert(!eth_check_link_change() && !mdio_calls);
    tick();assert(!eth_check_link_change() && !init_calls);
#ifdef CONFIG_IPQ5018_XIAOMI_RA80
    assert(LINK_CHECK_INTERVAL==1000 && mdio_calls==18);
#else
    assert(LINK_CHECK_INTERVAL==100 && mdio_calls==192);
#endif
    int previous=mdio_calls;
    assert(!eth_check_link_change() && mdio_calls==previous);
    live_bus=0;live_phy=7;tick();assert(eth_check_link_change()==1 && init_calls==1);
    tick();assert(!eth_check_link_change() && init_calls==1);
    live_bus=1;live_phy=4;tick();assert(eth_check_link_change()==1 && init_calls==2);
    previous=mdio_calls;tick();assert(!eth_check_link_change() && init_calls==2);
#ifdef CONFIG_IPQ5018_XIAOMI_RA80
    assert(mdio_calls-previous==16); /* one live spec read, five absent PHYs. */
#endif
    latched_low=1;tick();assert(!eth_check_link_change() && init_calls==2 && latched_low==2);
    read_error=1;tick();assert(!eth_check_link_change() && init_calls==2);
    read_error=0;live_bus=0;live_phy=7;latched_low=0;tick();
    assert(eth_check_link_change()==1 && init_calls==3);
    puts("PASS: production link monitor bounds MDIO reads, throttles scans, handles absent/error/latched-low PHYs, and reinitializes only on link changes");
}
'''
code = interval + prefix + function('static int read_phy_link(') + function('int eth_check_link_change(') + tests
with tempfile.TemporaryDirectory(prefix='ra80-rx-poll-') as tmp:
    test=Path(tmp)/'test.c';test.write_text(code)
    for target in ('CONFIG_IPQ5018_XIAOMI_RA80','CONFIG_IPQ5018'):
        exe=Path(tmp)/('test.exe' if os.name=='nt' else 'test')
        subprocess.run([os.environ.get('CC','cc'),'-std=c99','-Wall','-Wextra','-D'+target,str(test),'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True)
header=(root/'include/configs/ipq5018.h').read_text()
block=header.split('#ifdef CONFIG_IPQ5018_XIAOMI_RA80',1)[1].split('#endif',1)[0]
buffers=int(re.search(r'#define CONFIG_SYS_RX_ETH_BUFFER\s+(\d+)',block)[1])
assert buffers==32 and buffers>=2*8
print('PASS: RA80 RX ring contains 32 packet buffers, covering an 8-MSS TCP window plus a burst margin')
