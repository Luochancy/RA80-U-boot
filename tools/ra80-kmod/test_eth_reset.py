#!/usr/bin/env python3
"""Exercise actual GMAC reset/init and switch link code with fake MMIO/MDIO."""
import os
import subprocess
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[2]
source = (root/'drivers/net/ipq5018/ipq5018_gmac.c').read_text()

def function(signature):
    begin = source.index(signature)
    body = source.index('{', begin)
    depth = 1
    end = body + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[begin:end]

prefix = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <errno.h>
typedef uint32_t u32;
typedef unsigned int uint;
typedef struct { int unused; } bd_t;
#define DMAMAC_SRST 1
#define RXSTART 2
#define TXSTART 4
#define LINK_UP 0x400
#define LINK(v) "test"
#define SPEED(v) (((v)&0xc000)>>12)
#define SPEED_1000M (1<<3)
#define SPEED_100M (1<<2)
#define DUPLEX(v) "test"
struct eth_dma_regs { u32 busmode,status,txdesclistaddr,opmode; } dma;
struct board_cfg { int switch_port_count; int switch_port_phy_address[5]; } cfg;
struct ipq_eth_dev { void *dma_regs_p; int mac_unit; unsigned next_rx,next_tx;
    void *desc_tx[1]; struct board_cfg *gmac_board_cfg; } priv;
struct eth_device { void *priv; } dev;
static unsigned polls,clear_after,delay_calls,write_calls,config_calls;
static int phy_result,phy_values[5];
static void udelay(unsigned us) { assert(us==10); delay_calls++; }
static u32 readl(u32 *reg) {
    if(reg==&dma.busmode) {
        polls++;
        if(clear_after && polls>=clear_after) dma.busmode &= ~DMAMAC_SRST;
    }
    return *reg;
}
static void writel(u32 value,u32 *reg) { write_calls++; *reg=value; }
static void setbits_le32(u32 *reg,u32 value) { write_calls++; *reg |= value; }
static int ipq5018_phy_link_update(struct eth_device *d) { return phy_result; }
static int ipq_eth_wr_macaddr(struct eth_device *d) { config_calls++; return 0; }
static void ipq_eth_dma_cfg(struct eth_device *d) { config_calls++; }
static void ipq_eth_mac_cfg(struct eth_device *d) { config_calls++; }
static void ipq_eth_flw_cntl_cfg(struct eth_device *d) { config_calls++; }
static void ipq_gmac_rx_desc_setup(struct ipq_eth_dev *p) { config_calls++; }
static int ipq_mdio_read(int address,int reg,void *unused) {
    assert(reg==0x11 && address>=0 && address<5); return phy_values[address];
}
static void reset_fake(unsigned clear,int link) {
    dma=(struct eth_dma_regs){0};
    polls=delay_calls=write_calls=config_calls=0;
    clear_after=clear; phy_result=link;
    priv=(struct ipq_eth_dev){ .dma_regs_p=&dma,.gmac_board_cfg=&cfg };
    dev.priv=&priv;
}
'''
tests = r'''
int main(void) {
    reset_fake(0,0);
    assert(ipq_eth_init(&dev,NULL)==-ETIMEDOUT);
    assert(polls==10000 && delay_calls==10000 && write_calls==1);
    assert(config_calls==0); /* Do not start DMA after a stuck reset. */
    reset_fake(3,0);
    assert(ipq_eth_init(&dev,NULL)==1);
    assert(polls==3 && config_calls==5 && (dma.opmode&6)==6);
    reset_fake(10000,0);
    assert(ipq_mac_reset(&dev)==0 && polls==10000);
    reset_fake(0,-1);
    assert(ipq_eth_init(&dev,NULL)==-1 && polls==0 && write_calls==0);
    cfg.switch_port_count=5;
    for(int i=0;i<5;i++) { cfg.switch_port_phy_address[i]=i; phy_values[i]=-ETIMEDOUT; }
    assert(ipq5018_s17c_Link_Update(&priv)==1);
    for(int i=0;i<5;i++) phy_values[i]=0xffff;
    assert(ipq5018_s17c_Link_Update(&priv)==1);
    phy_values[2]=LINK_UP;
    assert(ipq5018_s17c_Link_Update(&priv)==0);
    puts("PASS: stuck reset returns, failure stops DMA, healthy reset succeeds, MDIO errors are not links");
    return 0;
}
'''
code = prefix + '\n'.join(function(s) for s in (
    'static int ipq_mac_reset(', 'int ipq_eth_init(',
    'static int ipq5018_s17c_Link_Update(')) + tests
with tempfile.TemporaryDirectory(prefix='ra80-gmac-test-') as tmp:
    test = Path(tmp)/'test.c'
    exe = Path(tmp)/('test.exe' if os.name=='nt' else 'test')
    test.write_text(code)
    subprocess.run([os.environ.get('CC','cc'),'-std=c99','-Wno-pointer-to-int-cast',str(test),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
