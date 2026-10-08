# RA80 RAM-only HTTP/链路细分测试

只上传 `ra80_ramboot_full.ko`，匹配的 U-Boot 已嵌入模块。不要另传 bin 或 trigger。
本版启用 CONFIG_RA80_LINK_DIAGNOSTICS，关闭运行期细分。
**B/E/F含义不变；0、3..A、C、D改为HTTP/链路内的固定阶段，请用本表。**

上一份c200032实机仍停E。旧E只证明网卡注册返回、即将调用httpd，不能证明HttpdStart已进入，更不能证明PHY、DMA或HTTP就绪。
本版只增加细分标记和进度锁存，保留已修复的复位超时、MDIO错误处理及重试；未猜测性修改PHY、VLAN或交换机寄存器。
RAM启动仍跳过NAND初始化、闪存环境与ART读取，使用临时本地管理MAC（02:52:41:38:30:10和:11）。
底层NAND写保护、禁用训练、禁止网页升级/命令、模块ABI与保留RAM边界校验全部保留。

设备为 **3 LAN + 1 WAN**。1=Internet，2=System。
GPIO17=2黄、19=2白、20=1黄、22=1白，均高电平亮；位0..3按17/19/20/22排列。
每灯有灭/黄/白/粉四种状态，组合共16种。粉指黄白两珠同时亮。
特别核对：B=17/19/22，1白2粉；E=19/20/22，1粉2白；F=四珠全亮，双粉。

| 码 | 1：Internet | 2：System | 最后到达的位置 / 停留含义 |
|---|---|---|---|
| 0 | 灭 | 灭 | DMA复位调用已返回，可能成功或超时；尚未观察到网卡active。经过前面的灯码后全灭是有效结果 |
| 1 | 灭 | 黄 | Linux预检完成、即将交接；尚未见U-Boot reset |
| 2 | 灭 | 白 | U-Boot reset；已验证过的早期初始化统一保持此码 |
| 3 | 灭 | 粉 | HttpdStart已进入，下一步net_init |
| 4 | 黄 | 灭 | net_init已返回，下一段IP设置、串口提示和lwIP初始化 |
| 5 | 黄 | 黄 | failsafe_lwip_init已返回并设置运行标志；不保证TCP监听创建成功 |
| 6 | 黄 | 白 | httpd命令成功返回且运行标志为真；等待进入CLI网络轮询 |
| 7 | 黄 | 粉 | 首次有效HTTP轮询已进入，下一段定时器及轮询前置处理 |
| 8 | 白 | 灭 | 即将执行eth_check_link_change；此调用内部也可能发起网卡初始化 |
| 9 | 白 | 黄 | eth_check_link_change已返回；下一段选择网卡及eth_init |
| A | 白 | 白 | ipq_eth_init已进入，即将执行PHY链路/速度更新 |
| B | 白 | 粉 | main_loop已进入；下一段CLI及RAM标记分支 |
| C | 粉 | 灭 | PHY链路/速度更新已返回，可能失败；成功才继续DMA复位 |
| D | 粉 | 黄 | ipq_mac_reset已进入；下一段写复位寄存器及最多约100ms读回等待 |
| E | 粉 | 白 | 网卡注册返回，即将调用httpd；若新模块仍停E，范围缩至命令派发到HttpdStart入口之前 |
| F | 粉 | 粉 | HTTP轮询观察到网卡active；仍需验证ARP、ping及网页收发 |

阶段顺序是 `1 → 2 → B → E → 3 → 4 → 5 → 6 → 7 → 8 → 9 → A → C → D → 0 → F`，不是十六进制大小顺序。
内部调用可能先到达更深阶段，因此部分码会跳过；快速经过的码肉眼也可能看不到。
每个阶段首次到达时更新，重复或较浅阶段不再写LED；到F后保持F。
没有人为停留、计数脉冲或循环闪烁。四个GPIO依次写入的极短过渡组合不算最终码。
最终颜色表示“最深已到达边界”，不能把返回码解释成该操作必然成功。

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
