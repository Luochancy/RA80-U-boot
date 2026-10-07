include $(TOPDIR)/rules.mk
include $(INCLUDE_DIR)/kernel.mk

PKG_NAME:=ra80-probe
PKG_RELEASE:=1

include $(INCLUDE_DIR)/package.mk

define KernelPackage/ra80-probe
  SUBMENU:=Other modules
  TITLE:=RA80 read-only U-Boot reserved-memory probe
  FILES:=$(PKG_BUILD_DIR)/ra80_probe.ko
endef

define KernelPackage/ra80-probe/description
 Read-only probe for Xiaomi RA80 V1 / IPQ5018 stock U-Boot reserved RAM.
endef

define Build/Prepare
	mkdir -p $(PKG_BUILD_DIR)
	$(CP) ./src/ra80_probe.c $(PKG_BUILD_DIR)/
	$(CP) ./src/Makefile $(PKG_BUILD_DIR)/
endef

define Build/Compile
	+$(KERNEL_MAKE) $(PKG_JOBS) M="$(PKG_BUILD_DIR)" modules
endef

$(eval $(call KernelPackage,ra80-probe))
