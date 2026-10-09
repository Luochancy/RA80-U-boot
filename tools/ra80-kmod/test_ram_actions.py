#!/usr/bin/env python3
"""Test actual upload/reset gates and kernel FDT fixup against host libfdt."""
import os,subprocess,tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[2]
def function(path, signature):
 s=(root/path).read_text();a=s.index(signature);b=s.index('{',a)+1;d=1
 while d:d+=(s[b]=='{')-(s[b]=='}');b+=1
 return s[a:b]
common='''#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <assert.h>
#include <stdlib.h>
typedef unsigned long ulong;
typedef uint64_t u64;
'''
fdt=common+'''
#include <libfdt.h>
#define CONFIG_SYS_SDRAM_BASE 0x40000000
struct { u64 ram_size; } global_data={0x10000000}, *gd=&global_data;
static int memory_result,memory_calls;
static int fdt_fixup_memory_banks(void *blob,u64 *start,u64 *size,int banks) {
 assert(*start==0x40000000 && *size==0x10000000 && banks==1);memory_calls++;return memory_result;
}
'''+function('board/qca/arm/common/fdt_fixup.c','static int ra80_ram_kernel_fdt(')+r'''
static int node(void *b,const char *path) { int n=fdt_path_offset(b,path);assert(n>=0);return n; }
int main(int argc,char **argv) {
 char input[8192], blob[16384];FILE *file=fopen(argv[1],"rb");assert(file);
 size_t n=fread(input,1,sizeof(input),file);fclose(file);assert(n);
 assert(!fdt_open_into(input,blob,sizeof(blob)));
 assert(!ra80_ram_kernel_fdt(blob) && memory_calls==1);
 const char *paths[]={"/soc/spi@79b0000","/soc/spi@79b0000/flash@0","/soc/mmc@7804000","/soc/wifi@c000000","/soc/remoteproc@cd00000"};
 for(unsigned i=0;i<5;i++)assert(!strcmp(fdt_getprop(blob,node(blob,paths[i]),"status",NULL),"disabled"));
 int chosen=node(blob,"/chosen");const char *args=fdt_getprop(blob,chosen,"bootargs",NULL);
 assert(args && strstr(args,"rdinit=/sbin/init") && !strstr(args,"ubi") && !strstr(args,"ubiblock"));
 assert(!fdt_getprop(blob,chosen,"bootargs-append",NULL));
 assert(!fdt_getprop(blob,chosen,"bootargs-override",NULL));
 assert(!fdt_getprop(blob,node(blob,"/soc/ethernet@39d00000"),"nvmem-cells",NULL));
 assert(!fdt_getprop(blob,node(blob,"/soc/ethernet@39d00000"),"nvmem-cell-names",NULL));
 assert(fdt_getprop(blob,node(blob,"/soc/cpu-calibration"),"nvmem-cells",NULL));
 assert(!strcmp(fdt_getprop(blob,node(blob,"/soc/ethernet@39d00000"),"status",NULL),"okay"));
 assert(!fdt_open_into(input,blob,sizeof(blob)));memory_result=-FDT_ERR_NOSPACE;
 assert(ra80_ram_kernel_fdt(blob)==-FDT_ERR_NOSPACE);memory_result=0;
 assert(!fdt_setprop_string(blob,0,"compatible","wrong,board"));
 assert(ra80_ram_kernel_fdt(blob)==-FDT_ERR_BADVALUE);
 puts("PASS: actual kernel fixup disables NAND/MMC/Wi-Fi, removes flash bootargs, preserves Ethernet and unrelated nvmem, rejects errors/wrong boards");
}
'''
fixture=r'''/dts-v1/;
/ { compatible="xiaomi,ax3000";
 chosen { bootargs="ubi.mtd=rootfs";bootargs-append="root=/dev/ubiblock0_1";bootargs-override="bad"; };
 soc {
  spi@79b0000 { compatible="qcom,ipq5018-snand","qcom,ipq9574-snand";status="okay"; flash@0 { compatible="spi-nand"; }; };
  mmc@7804000 { compatible="qcom,ipq5018-sdhci";status="okay"; };
  wifi@c000000 { compatible="qcom,ipq5018-wifi";status="okay"; };
  remoteproc@cd00000 { compatible="qcom,ipq5018-wcss-pil";status="okay"; };
  ethernet@39d00000 { compatible="qcom,nss-dp";status="okay";nvmem-cells=<1>;nvmem-cell-names="mac-address"; };
  cpu-calibration { nvmem-cells=<2>;nvmem-cell-names="speed-bin"; };
 };
};'''
gate=common+r'''
struct fdt_header { uint32_t words[10]; };
#define CONFIG_SYS_BOOTM_LEN 0x4000000UL
#define CONFIG_SYS_SDRAM_END 0x50000000UL
#define UPLOAD_ADDR 0x4b000000UL
#define RAM_BOOT_ADDR 0x44000000UL
#define WEBFAILSAFE_PROGRESS_UPGRADING 2
enum { WEBFAILSAFE_UPGRADE_TYPE_FIRMWARE=1,WEBFAILSAFE_UPGRADE_TYPE_UBOOT,WEBFAILSAFE_UPGRADE_TYPE_ART,WEBFAILSAFE_UPGRADE_TYPE_IMG,WEBFAILSAFE_UPGRADE_TYPE_CDT,WEBFAILSAFE_UPGRADE_TYPE_MIBIB,WEBFAILSAFE_UPGRADE_TYPE_PTABLE,WEBFAILSAFE_UPGRADE_TYPE_INITRAMFS };
static int ram=1,header_error,path_error,copies,boots,flashcalls;
static ulong totalsize=1000;
static int ra80_ram_test_active(void){return ram;}
static int fdt_check_header(void *p){assert((ulong)p==UPLOAD_ADDR);return header_error;}
static ulong fdt_totalsize(void *p){return totalsize;}
static int fdt_path_offset(void *p,const char *name){return path_error?-1:0;}
static void printChecksumMd5(ulong p,ulong size){}
static void do_http_progress(int stage){}
static void *fake_memmove(void *dst,const void *src,size_t size){assert((ulong)dst==RAM_BOOT_ADDR && (ulong)src==UPLOAD_ADDR);copies++;return dst;}
#define memmove fake_memmove
static int do_initramfs_boot(ulong size){boots++;return -1;}
#define FLASH_STUB(name) static int name(ulong size){flashcalls++;return 0;}
FLASH_STUB(do_firmware_upgrade) FLASH_STUB(do_uboot_upgrade) FLASH_STUB(do_art_upgrade)
FLASH_STUB(do_img_upgrade) FLASH_STUB(do_cdt_upgrade) FLASH_STUB(do_mibib_upgrade) FLASH_STUB(do_ptable_upgrade)
'''+function('net/httpd.c','int do_http_upgrade(')+r'''
int main(void) {
 for(int type=1;type<WEBFAILSAFE_UPGRADE_TYPE_INITRAMFS;type++)assert(do_http_upgrade(1000,type)==-1);
 assert(!flashcalls && !copies && !boots);
 ulong sizes[]={0,39,CONFIG_SYS_BOOTM_LEN+1,~0UL};
 for(unsigned i=0;i<4;i++)assert(do_http_upgrade(sizes[i],WEBFAILSAFE_UPGRADE_TYPE_INITRAMFS)==-1);
 header_error=1;assert(do_http_upgrade(1000,8)==-1);header_error=0;
 path_error=1;assert(do_http_upgrade(1000,8)==-1);path_error=0;
 totalsize=999;assert(do_http_upgrade(1000,8)==-1);totalsize=1000;
 assert(!copies && !boots);
 assert(do_http_upgrade(1000,8)==-1 && copies==1 && boots==1 && !flashcalls);
 ram=0;assert(do_http_upgrade(1000,1)==0 && flashcalls==1);
 puts("PASS: actual RAM upload gate allows only bounded FIT initramfs; flash/malformed/oversize inputs cause no copy or flash call");
}
'''
boot=common+r'''
#define RAM_BOOT_ADDR 0x44000000UL
#define FW_TYPE_FIT 0
static int ram=1,type,boots,commands,boot_result;
static int ra80_ram_test_active(void){return ram;}
static int check_fw_type(void *p){assert((ulong)p==RAM_BOOT_ADDR);return type;}
static const char *fw_type_to_string(int type){return "test";}
static void print_upgrade_warning(const char *s){}
static int execute_command(const char *s){commands++;return 0;}
static int do_bootm(void *cmd,int flag,int argc,char *const argv[]){
 assert(!cmd && !flag && argc==2 && !strcmp(argv[0],"bootm") && !strcmp(argv[1],"44000000") && !argv[2]);boots++;return boot_result;
}
'''+function('net/httpd.c','static int do_initramfs_boot(const ulong size) {')+r'''
int main(void) {
 type=1;assert(do_initramfs_boot(1000)==-1 && !boots && !commands);type=0;
 boot_result=1;assert(do_initramfs_boot(1000)==-1 && boots==1 && !commands);
 boot_result=0;assert(do_initramfs_boot(1000)==-1 && boots==2 && !commands);
 ram=0;assert(do_initramfs_boot(1000)==0 && commands==1);
 puts("PASS: actual RAM initramfs invokes bootm directly without parser and treats every returned handoff as failure");
}
'''
reset=common+r'''
#define WEBTERM_BUFFER_SIZE 1024
static char webterm_output_buf[1024],webterm_pending_cmd[1024];
static int webterm_has_pending_cmd,webterm_abort_requested,webterm_line_pos,webfailsafe_is_running=1,ram=1,resets,commands;
static int ra80_ram_test_active(void){return ram;}
static void webterm_capture_output(const char *s){}
static void webterm_flush_line(void){}
static int do_reset(void *cmd,int flag,int argc,void *argv){resets++;return 0;}
static int run_command(const char *s,int flag){commands++;return 0;}
'''+function('common/webterm.c','void webterm_execute_command(')+'\n'+function('common/webterm.c','int webterm_run_pending_command(')+r'''
int main(void) {
 const char *bad[]={"nand erase","saveenv","reset; nand erase","reset now"," reset","reset\n"};
 for(unsigned i=0;i<6;i++){webterm_execute_command(bad[i]);assert(!webterm_has_pending_cmd && !resets && !commands);}
 webterm_execute_command("reset");assert(webterm_has_pending_cmd && !resets);
 assert(webterm_run_pending_command()==1 && resets==1 && !commands && !webterm_has_pending_cmd);
 assert(webterm_run_pending_command()==0 && resets==1);
 strcpy(webterm_pending_cmd,"nand erase");webterm_has_pending_cmd=1;
 assert(webterm_run_pending_command()==0 && !commands && resets==1);
 webfailsafe_is_running=0;webterm_execute_command("reset");assert(resets==2 && !commands);
 ram=0;webterm_execute_command("version");assert(commands==1);
 puts("PASS: actual RAM web reset queues/directly resets once without Hush; arbitrary commands and injected suffixes remain denied");
}
'''
with tempfile.TemporaryDirectory(prefix='ra80-actions-') as tmp:
 tmp=Path(tmp);(tmp/'fixture.dts').write_text(fixture)
 subprocess.run(['dtc','-I','dts','-O','dtb','-o',str(tmp/'fixture.dtb'),str(tmp/'fixture.dts')],check=True)
 for name,code in [('fdt',fdt),('gate',gate),('boot',boot),('reset',reset)]:
  src=tmp/(name+'.c');exe=tmp/name;src.write_text(code)
  subprocess.run([os.environ.get('CC','cc'),'-D_GNU_SOURCE','-std=c99','-Wall',str(src),'-o',str(exe)]+(['-lfdt'] if name=='fdt' else []),check=True)
  subprocess.run([str(exe)]+([str(tmp/'fixture.dtb')] if name=='fdt' else []),check=True)
