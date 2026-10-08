include $(TOPDIR)/rules.mk
include $(INCLUDE_DIR)/kernel.mk

PKG_NAME:=ra80-stage-ethdiag
PKG_RELEASE:=1

include $(INCLUDE_DIR)/package.mk

define KernelPackage/ra80-stage-ethdiag
  SUBMENU:=Other modules
  TITLE:=RA80 reversible RAM-only U-Boot diagnostic stage
  FILES:=$(PKG_BUILD_DIR)/ra80_stage_ethdiag.ko
endef

define KernelPackage/ra80-stage-ethdiag/description
 Reversible RAM-only stage for the Xiaomi RA80 V1 LED-diagnostic U-Boot.
 This module has no automatic jump and contains no NAND/MTD write path.
endef

define Build/Prepare
	mkdir -p $(PKG_BUILD_DIR)
	$(CP) ./src/ra80_stage_ethdiag.c $(PKG_BUILD_DIR)/
	$(CP) ./src/ra80_payload.inc $(PKG_BUILD_DIR)/
	$(CP) ./src/Makefile $(PKG_BUILD_DIR)/
endef

define Build/Compile
	+$(KERNEL_MAKE) $(PKG_JOBS) M="$(PKG_BUILD_DIR)" modules
endef

$(eval $(call KernelPackage,ra80-stage-ethdiag))
