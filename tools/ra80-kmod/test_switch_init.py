#!/usr/bin/env python3
"""Run extracted production MDIO/switch functions with transport fault injection."""
import os
import subprocess
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[2]
def function(path, signature):
    text=(root/path).read_text()
    start=text.index(signature); end=text.index('{',start)+1; depth=1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}');end+=1
    return text[start:end]

common=r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <errno.h>
typedef uint32_t u32;
typedef unsigned short ushort;
'''
mdio=common+r'''
#define IPQ_MDIO_RETRY 1000
#define IPQ_MDIO_DELAY 5
#define IPQ_MDIO_BASE 0x90000
#define MDIO_CTRL_4_REG 0x50
#define MDIO_CTRL_4_ACCESS_BUSY (1<<16)
static unsigned delayed, reads, clear_at;
static void udelay(unsigned us) { assert(us==5); delayed+=us; }
static u32 readl(unsigned address) {
    assert(address==0x90050);reads++;
    return clear_at && delayed>=clear_at ? 0 : MDIO_CTRL_4_ACCESS_BUSY;
}
'''+function('drivers/net/ipq_common/ipq_mdio.c','static int ipq_mdio_wait_busy(')+r'''
int main(void) {
    clear_at=200; assert(ipq_mdio_wait_busy()==0 && delayed==200 && reads==40);
    delayed=reads=0; clear_at=5000;
    assert(ipq_mdio_wait_busy()==0 && reads==1000);
    delayed=reads=clear_at=0;
    assert(ipq_mdio_wait_busy()==-ETIMEDOUT && reads==1000 && delayed==5000);
    puts("PASS: actual MDIO loop waits for wire completion, accepts final poll, times out bounded");
}
'''
ath='drivers/net/ipq5018/athrs17_phy.c'
registers=common+r'''
static int athrs17_mdio_error, operation, fail_at;
static unsigned page_delays;
static void udelay(unsigned us) { assert(us==5);page_delays++; }
static int ipq_mdio_write(int phy,int reg,uint16_t value) {
    return ++operation==fail_at ? -ETIMEDOUT : 0;
}
static int ipq_mdio_read(int phy,int reg,uint16_t *value) {
    if(++operation==fail_at)return -ETIMEDOUT;
    *value=reg&1 ? 0x1234 : 0x5678;return *value;
}
'''+ '\n'.join(function(ath,s) for s in (
    'static int athrs17_mdio_write(', 'static int athrs17_mdio_read(',
    'static uint32_t\nathrs17_reg_read(', 'static void\nathrs17_reg_write('))+r'''
int main(void) {
    for(int i=1;i<=3;i++) {
        operation=athrs17_mdio_error=0;fail_at=i;
        assert(athrs17_reg_read(0)==0xffffffff && athrs17_mdio_error==-ETIMEDOUT);
        assert(operation==i);
        operation=athrs17_mdio_error=0;
        athrs17_reg_write(0,0x12345678);
        assert(athrs17_mdio_error==-ETIMEDOUT && operation==i);
    }
    operation=athrs17_mdio_error=fail_at=page_delays=0;
    assert(athrs17_reg_read(0)==0x12345678 && page_delays==1);
    athrs17_reg_write(0,0x12345678);assert(page_delays==2 && !athrs17_mdio_error);
    puts("PASS: actual switch register access propagates errors at page/low/high operations and settles page");
}
'''
reset=common+r'''
#define S17_MASK_CTRL_REG 0
#define S17_GLOBAL_INT0_REG 0x20
#define S17_MASK_CTRL_SOFT_RET (1u<<31)
#define S17_GLOBAL_INITIALIZED_STATUS 0xff
static int athrs17_mdio_error, transport_fail;
static unsigned polls[2], ready[2], elapsed;
static void udelay(unsigned us) { assert(us==1000);elapsed+=us; }
static void athrs17_reg_write(uint32_t reg,uint32_t value) {
    assert(reg==0 && value==S17_MASK_CTRL_SOFT_RET);
    if(transport_fail==1)athrs17_mdio_error=-EIO;
}
static uint32_t athrs17_reg_read(uint32_t reg) {
    unsigned n=reg==S17_GLOBAL_INT0_REG;
    if(transport_fail==2)athrs17_mdio_error=-ETIMEDOUT;
    polls[n]++;
    if(n)return ready[n] && polls[n]>=ready[n] ? 0xff : 0;
    return ready[n] && polls[n]>=ready[n] ? 0 : S17_MASK_CTRL_SOFT_RET;
}
static void setup(unsigned a,unsigned b,int fail) {
    polls[0]=polls[1]=elapsed=0;ready[0]=a;ready[1]=b;transport_fail=fail;
}
'''+function(ath,'int athrs17_init_switch(void)')+r'''
int main(void) {
    setup(1000,1000,0);assert(athrs17_init_switch()==0 && polls[0]==1000 && polls[1]==1000);
    setup(0,1,0);assert(athrs17_init_switch()==-ETIMEDOUT && polls[0]==1000 && !polls[1]);
    setup(1,0,0);assert(athrs17_init_switch()==-ETIMEDOUT && polls[1]==1000);
    setup(1,1,1);assert(athrs17_init_switch()==-EIO && !polls[0]);
    setup(1,1,2);assert(athrs17_init_switch()==-ETIMEDOUT && polls[0]==1);
    setup(10,20,0);assert(athrs17_init_switch()==0 && elapsed==30000);
    puts("PASS: actual switch reset accepts late/final completion, preserves MDIO failures, bounds both phases");
}
'''
gmac='drivers/net/ipq5018/ipq5018_gmac.c'
switch=common+r'''
#define MII_BMCR 0
#define BMCR_PDOWN 0x800
#define BMCR_RESET 0x8000
#define BMCR_ANENABLE 0x1000
#define MII_ADVERTISE 4
#define MII_CTRL1000 9
#define ADVERTISE_ALL 0x1e0
#define ADVERTISE_PAUSE_CAP 0x400
#define ADVERTISE_PAUSE_ASYM 0x800
#define ADVERTISE_1000FULL 0x200
typedef struct { int switch_port_count; int switch_port_phy_address[5]; } ipq_gmac_board_cfg_t;
static unsigned delay_ms, ready_ms;
static int writes, reads, fail_write, fail_read, core_result, debug_select[5];
static void mdelay(unsigned ms) { assert(ms==20);delay_ms+=ms; }
static int ipq_mdio_write(int phy,int reg,unsigned value) {
    assert(phy>=0 && phy<5 && reg<32);
    if(++writes==fail_write)return -ETIMEDOUT;
    if(reg==0x1d) { assert(value==0x3d || value==0xb);debug_select[phy]=value; }
    if(reg==0x1e)assert(debug_select[phy]);
    return 0;
}
static int ipq_mdio_read(int phy,int reg,void *unused) {
    if(++reads==fail_read)return -ETIMEDOUT;
    if(reg==0x1e) { assert(debug_select[phy]);return 0x2440; }
    assert(reg==MII_BMCR);return ready_ms && delay_ms>=ready_ms ? 0 : BMCR_RESET;
}
static int ipq_athrs17_init(ipq_gmac_board_cfg_t *cfg) { return core_result; }
static void setup(unsigned ready,int fw,int fr,int core) {
    delay_ms=writes=reads=0;ready_ms=ready;fail_write=fw;fail_read=fr;core_result=core;
}
'''+ '\n'.join(function(gmac,s) for s in (
    'static int ra80_switch_debug_clear(', 'static int ra80_switch_init('))+r'''
int main(void) {
    ipq_gmac_board_cfg_t cfg={5,{0,1,2,3,4}};
    setup(600,0,0,0);assert(ra80_switch_init(&cfg)==1 && delay_ms==600);
    setup(0,0,0,0);assert(ra80_switch_init(&cfg)==0 && delay_ms==600);
    for(int i=1;i<=40;i++) { setup(20,i,0,0);assert(ra80_switch_init(&cfg)==0); }
    for(int i=1;i<=15;i++) { setup(20,0,i,0);assert(ra80_switch_init(&cfg)==0); }
    setup(20,0,0,-EIO);assert(ra80_switch_init(&cfg)==0 && !delay_ms);
    setup(20,0,0,0);assert(ra80_switch_init(&cfg)==1 && delay_ms==20);
    puts("PASS: actual RA80 setup uses indirect debug registers, checks every transaction, bounds PHY reset");
}
'''
with tempfile.TemporaryDirectory(prefix='ra80-switch-test-') as tmp:
    for name,code in [('mdio',mdio),('registers',registers),('reset',reset),('switch',switch)]:
        src=Path(tmp)/(name+'.c');exe=Path(tmp)/(name+('.exe' if os.name=='nt' else ''))
        src.write_text(code)
        subprocess.run([os.environ.get('CC','cc'),'-std=c99','-Wall',str(src),'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True)
