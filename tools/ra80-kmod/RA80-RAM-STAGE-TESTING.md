# RA80 RAM-only 固定灯码测试

只上传 `ra80_ramboot_full.ko`，匹配的 U-Boot 已嵌入模块。不要另传 bin 或 trigger。
本版取消启动阶段闪烁、计数脉冲和人为停留；快速经过的码可能肉眼看不到。
停住后的两个灯表示最后到达的位置，不能单凭亮灯认定启动成功。

设备为 **3 LAN + 1 WAN**。1 是 Internet，2 是 System。
GPIO17=2黄、19=2白、20=1黄、22=1白，均高电平亮。
每灯有灭/黄/白/黄白同时亮四种电气状态，组合共16种。
黄白同时亮可能看起来接近白色，观察两颗灯珠，不把它称为蓝色。

| 码 | 1：Internet | 2：System | 最后到达的位置 / 随后执行的范围 |
|---|---|---|---|
| 0 | 灭 | 灭 | 保留：未标记，不能判断启动位置 |
| 1 | 灭 | 黄 | Linux 已完成预检，准备交接；若停在这里，尚未见到 U-Boot reset |
| 2 | 灭 | 白 | 进入 U-Boot reset；下一段是参数保存与 CPU 设置 |
| 3 | 灭 | 黄白同时亮 | 进入 _main；下一段建立初始栈和 GD |
| 4 | 黄 | 灭 | 初始栈/GD 建立；下一段清 BSS 和早期初始化 |
| 5 | 黄 | 黄 | 进入控制 FDT 初始化；下一段 SMEM/解压/选择/校验 FDT |
| 6 | 黄 | 白 | 控制 FDT 校验通过；下一段早期内存、设备模型、定时器、串口 |
| 7 | 黄 | 黄白同时亮 | 控制台初始化返回；下一段 DRAM、内存布局和运行期 GD |
| 8 | 白 | 灭 | board_init_f 返回；下一段切换栈/GD 和运行期 CPU 设置 |
| 9 | 白 | 黄 | 进入 board_init_r；下一段运行期初始化和 cache 启用 |
| A | 白 | 白 | cache 启用返回；下一段堆、存储读取、环境和其余驱动初始化 |
| B | 白 | 黄白同时亮 | 进入 main_loop；下一段 CLI 与 RAM-only marker 分支 |
| C | 黄白同时亮 | 灭 | 进入 board_eth_init；下一段网口时钟、GPIO、板级 GMAC 配置 |
| D | 黄白同时亮 | 黄 | 进入 ipq_gmac_init；下一段 MDIO/PHY/交换机/GMAC 注册 |
| E | 黄白同时亮 | 白 | 网卡注册阶段返回，进入 HTTP/链路启动；不等于物理链路已经可用 |
| F | 黄白同时亮 | 黄白同时亮 | HTTP 轮询已观察到网卡 active；仍需验证 ARP、ping 和网页数据通路 |

## 执行一次完整测试

1. 断电重启回原厂 Linux。电脑端用 `Get-FileHash` 核对模块 SHA256 与 `inspection.txt`。
   如果路由器没有 sha256sum，可用 `md5sum` 与下载包中的 MD5 对照。
2. 上传新模块到 `/tmp/ra80_ramboot_full.ko`，先确认原厂 RAM 向量为 `0xEA0000B8`。

```sh
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
4. 测试三个 LAN；WAN 可额外测试，不保证其交换机 VLAN 能通 CPU。
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
