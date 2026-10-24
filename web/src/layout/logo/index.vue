<template>
	<div class="layout-logo" v-if="setShowLogo" @click="onThemeConfigChange">
		<!-- 注释编号: django-vue3-admin_index471115:取消主页左上角logo -->
		<!-- <img :src="logoMini" class="layout-logo-medium-img" /> -->

		<!--  注释编号:django-vue3-admin__index531415:修改主页的名称 -->
		<!-- <span style="font-size: x-large">{{ themeConfig.globalTitle }}</span> -->

		<!-- 主题色方块（暖白是陶土色渐变）里画一个刀盘图形 -->
		<span class="layout-logo__mark" aria-hidden="true">
			<svg viewBox="0 0 24 24" width="17" height="17">
				<circle cx="12" cy="12" r="8.6" fill="none" stroke="currentColor" stroke-width="1.8" />
				<path d="M12 3.4v17.2M4.55 7.7l14.9 8.6M4.55 16.3l14.9-8.6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
				<circle cx="12" cy="12" r="2.6" fill="currentColor" />
			</svg>
		</span>
		<div class = "layout-logo__text">
			<span class = "layout-logo__title">盾构刀具管理系统</span>
			<span class = "layout-logo__subtitle">Information Management System of Shield Tunnel Cutter</span>
		</div>

	</div>

	<!-- 注释编号:django-vue3-admin__index471615:取消主页左上角logo -->
	<!-- <div class="layout-logo-size" v-else @click="onThemeConfigChange">
		<img :src="logoMini" class="layout-logo-size-img" />
	</div> -->
</template>

<script setup lang="ts" name="layoutLogo">
import { computed } from 'vue';
import { storeToRefs } from 'pinia';
import { useThemeConfig } from '/@/stores/themeConfig';
import logoMini from '/@/assets/logo-mini.svg';  // 注释编号:django-vue3-admin__index181215:取消主页左上角的logo
import { SystemConfigStore } from "/@/stores/systemConfig";
import _ from "lodash-es";
// 定义变量内容
const storesThemeConfig = useThemeConfig();
const { themeConfig } = storeToRefs(storesThemeConfig);

// 设置 logo 的显示。classic 经典布局默认显示 logo
const setShowLogo = computed(() => {
	let { isCollapse, layout } = themeConfig.value;
	return !isCollapse || layout === 'classic' || document.body.clientWidth < 1000;
});
// logo 点击实现菜单展开/收起
const onThemeConfigChange = () => {
	if (themeConfig.value.layout === 'transverse') return false;
	themeConfig.value.isCollapse = !themeConfig.value.isCollapse;
};

const systemConfigStore = SystemConfigStore()
const { systemConfig } = storeToRefs(systemConfigStore)
const getSystemConfig = computed(() => {
	return systemConfig.value
})

const siteLogo = computed(() => {
	if (!_.isEmpty(getSystemConfig.value['login.site_logo'])) {
		return getSystemConfig.value['login.site_logo']
	}
	return logoMini
});

</script>

<style scoped lang="scss">
// 32px 主题色方块 + 系统名称（标题字体）+ 英文名
// 侧边栏布局放在侧栏顶部；经典、横向布局放在顶栏左侧，高度跟顶栏一致
.layout-logo {
	min-height: 50px;
	flex: none;
	display: flex;
	align-items: center;
	gap: 10px;
	padding: 4px 16px;
	cursor: pointer;
	animation: logoAnimation 0.3s ease-in-out;

	&__mark {
		width: 32px;
		height: 32px;
		flex: none;
		display: flex;
		align-items: center;
		justify-content: center;
		border-radius: 10px;
		color: var(--dv-on-primary);
		background: var(--dv-logo-bg);
		box-shadow: var(--dv-shadow-logo);
	}
	&__text {
		min-width: 0;
		max-width: 210px; // 英文名最多折成两行，放进 50px 高的顶栏
		display: flex;
		flex-direction: column;
		line-height: 1.25;
	}
	&__title {
		font-family: var(--dv-font-title);
		font-size: 14px;
		font-weight: 600;
		color: var(--dv-text);
		white-space: nowrap;
	}
	&__subtitle {
		font-size: 11px;
		line-height: 1.2;
		color: var(--dv-text-secondary);
	}

	&-medium-img {
		width: 40px;
		margin-right: 5px;
	}
}
// 方块左边离侧栏 12px（侧栏内边距 8px + 4px），中线与下面的菜单图标对齐
.layout-aside-panel .layout-logo {
	min-height: 0;
	padding: 4px 4px 12px;
}

.layout-logo-size {
	width: 100%;
	height: 50px;
	display: flex;
	cursor: pointer;
	animation: logoAnimation 0.3s ease-in-out;

	&-img {
		width: 40px;
		margin: auto;
	}

	&:hover {
		img {
			animation: logoAnimation 0.3s ease-in-out;
		}
	}
}
</style>
