include $(TOPDIR)/rules.mk
include $(INCLUDE_DIR)/kernel.mk

PKG_NAME:=ra80-ramboot-full
PKG_RELEASE:=1

include $(INCLUDE_DIR)/package.mk

define KernelPackage/ra80-ramboot-full
  SUBMENU:=Other modules
  TITLE:=RA80 guarded one-shot RAM-only U-Boot handoff
  FILES:=$(PKG_BUILD_DIR)/ra80_ramboot_full.ko
endef

define KernelPackage/ra80-ramboot-full/description
 One-shot RAM-only U-Boot handoff for Xiaomi RA80 V1 stock Linux 4.4.60.
 It validates, backs up, stages, verifies, arms Webfailsafe, and jumps without
 any NAND, MTD, UBI, or APPSBL operation.
endef

define Build/Prepare
	mkdir -p $(PKG_BUILD_DIR)
	$(CP) ./src/ra80_ramboot_full.c $(PKG_BUILD_DIR)/
	$(CP) ./src/ra80_payload.inc $(PKG_BUILD_DIR)/
	$(CP) ./src/Makefile $(PKG_BUILD_DIR)/
endef

define Build/Compile
	+$(KERNEL_MAKE) $(PKG_JOBS) M="$(PKG_BUILD_DIR)" modules
endef

$(eval $(call KernelPackage,ra80-ramboot-full))
