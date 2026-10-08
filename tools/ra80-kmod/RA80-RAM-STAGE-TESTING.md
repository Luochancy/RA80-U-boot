# RA80 RAM-only 直接网络启动测试

只上传 `ra80_ramboot_full.ko`；匹配U-Boot已嵌入，无需bin或trigger。
本版根据0f85c5a实机停B修正RAM启动路径。MD5已确认匹配，该B早于网卡注册返回E。
此前B到E包含Hush初始化、串口输出、RAM环境设置、延迟网卡注册。
**Hush在include/configs/ipq5018.h中定义，不能单看.config认定它关闭。**
新RAM路径从main_loop直接进入独立网络循环，跳过CLI初始化、命令解析、控制台等待和自动启动。
GD_FLG_DISABLE_CONSOLE仅在RAM模式设置；HttpdStart直接调用，随后持续httpd_poll。
网卡只注册一次。无设备、环境设置失败或HTTP运行标志未设置时保持当前码并停止，不退回自动启动。

另修复一条遗漏路径：board_eth_init在GMAC注册后调用board_update_caldata，后者可能读取ART并执行XO校准SCM。
RAM模式现跳过该调用；board_update_caldata和get_eth_caldata本身也在存储/SCM调用前拒绝RAM路径。
沿用Linux已经建立的校准状态，不凭空猜测校准寄存器。
此为可证实的源码缺口；不能据B断言实机已经执行到该读取。
GMAC局部设备指针数组初始化为0，并限制注册数量，防止分配失败清理未初始化指针或数组越界。
NAND训练禁用、底层写保护、临时MAC、复位上限、MDIO错误处理及网络重试保留。
本测试不写NAND/APPSBL。

**本版B/E/F、0/C/D含义保持；3..9与A更新为下表。请不要沿用0f85c5a的表。**
设备3 LAN + 1 WAN。1=Internet，2=System；粉=黄白两珠同时亮。
GPIO17=2黄、19=2白、20=1黄、22=1白，均高电平亮，bit0..3按此顺序。

| 码 | 1：Internet | 2：System | 最后到达的位置 / 停留含义 |
|---|---|---|---|
| 0 | 灭 | 灭 | DMA复位调用已返回，可能成功或超时；未观察到active |
| 1 | 灭 | 黄 | Linux预检完成、准备交接 |
| 2 | 灭 | 白 | U-Boot reset及早期初始化 |
| 3 | 灭 | 粉 | 进入直接RAM网络路径，准备设置RAM环境 |
| 4 | 黄 | 灭 | RAM环境准备返回，即将注册网卡 |
| 5 | 黄 | 黄 | 进入board_eth_init，下一段板级网口时钟/GPIO/FDT配置 |
| 6 | 黄 | 白 | 进入ipq_gmac_init，下一段MDIO/PHY/交换机/描述符及设备注册 |
| 7 | 黄 | 粉 | ipq_gmac_init调用返回，可能成功或失败；RAM模式跳过ART校准 |
| 8 | 白 | 灭 | 进入HttpdStart，下一段net_init/IP/DHCP/lwIP初始化 |
| 9 | 白 | 黄 | lwIP初始化返回且HTTP运行标志设置；不保证TCP监听成功 |
| A | 白 | 白 | 进入HTTP轮询，下一段定时器、链路变化检测和网卡初始化 |
| B | 白 | 粉 | 进入main_loop，即将直接进入RAM网络路径 |
| C | 粉 | 灭 | PHY链路/速度更新返回，可能成功或失败 |
| D | 粉 | 黄 | 进入DMA复位，最多约100ms等待自清 |
| E | 粉 | 白 | 网卡注册调用返回；没有可用网卡会停E，有网卡才进入HTTP |
| F | 粉 | 粉 | HTTP轮询观察到网卡active；仍需验证ARP/ping/网页 |

进度顺序：`1 → 2 → B → 3 → 4 → 5 → 6 → 7 → E → 8 → 9 → A → C → D → 0 → F`。
每个阶段首次到达才更新，只保留最深序号。没有闪烁、脉冲计数或人为停留；快速阶段可能看不到。
四个GPIO依次写入产生的极短过渡不算最终码。全灭0是有效结果。

## 执行一次完整测试

1. 断电重启回原厂 Linux，按包内MD5SUMS核对模块MD5。
   如果路由器没有 sha256sum，可用 `md5sum` 与下载包中的 MD5 对照。
2. 上传新模块到 `/tmp/ra80_ramboot_full.ko`，先确认原厂 RAM 向量为 `0xEA0000B8`。

```sh
md5sum /tmp/ra80_ramboot_full.ko
devmem 0x4a920000 32
sync
insmod /tmp/ra80_ramboot_full.ko execute=1
```

模块先备份、写入并读回校验 RAM，验证原厂内核地址/指令与 watchdog 指纹，
随后保持码1并倒计时3秒交接。SSH 会断开。此后不使用 Linux SSH 判断 U-Boot。
未交接前发生错误会尝试恢复原厂 RAM；交接后只能断电重启恢复原厂启动。

3. 电脑以太网设置 `192.168.1.2/24`，关闭 Wi-Fi/VPN。等约30秒，记录最后的
   **1灯颜色、2灯颜色**。这是观察时间，不保证硬件一定在30秒内初始化完成；
   固定码持续不变时，继续等5分钟不会提供更细的阶段信息。
4. 先测试当前LAN口；若F但数据不通，再记录口位置并检查其他LAN。
   测试 `ping 192.168.1.1` 和 `http://192.168.1.1/`。
   “以太网已连接”只表示电脑与 PHY 有链路，不代表 CPU/GMAC 收发正常。
5. 报告两灯最终状态、接的哪个口、ping/网页结果。然后断电重启回原厂。

诊断模式跳过 preboot、自动 TFTP 更新和自动启动；网页启动失败保留灯码并停止。
网页升级和网页命令执行已禁止。不要上传固件、执行 flash/nand/saveenv 等写入命令。
本测试不写 NAND/MTD/APPSBL；模块只修改保留 RAM、LED 和交接所需状态。

若 insmod 报错，不要继续交接，保留以下输出：
```sh
dmesg | grep 'ra80_ramboot_full:' | tail -50
devmem 0x4a920000 32
```

`led_test=1` 仅保留为单独的可恢复灯珠校准模式，不与 execute=1 合用；无需再校准。
详细审查结论在 `RA80-SOURCE-REVIEW.md`，产物验证在 `bootstage-verification.txt`。
