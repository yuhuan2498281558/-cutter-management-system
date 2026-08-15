<template>
	<div class="layout-logo" v-if="setShowLogo" @click="onThemeConfigChange">
		<!-- 注释编号: django-vue3-admin_index471115:取消主页左上角logo -->
		<!-- <img :src="logoMini" class="layout-logo-medium-img" /> -->

		<!--  注释编号:django-vue3-admin__index531415:修改主页的名称 -->
		<!-- <span style="font-size: x-large">{{ themeConfig.globalTitle }}</span> -->

		<div class = "layout-logo__text">
			<span class = "layout-logo__title">盾构隧道刀具管理系统</span><br>
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
.layout-logo {
	width: 220px;
	height: 50px;
	display: flex;
	align-items: center;
	justify-content: center;
	box-shadow: rgb(0 21 41 / 2%) 0px 1px 4px;
	color: var(--el-color-primary);
	font-size: 5px;
	cursor: pointer;
	animation: logoAnimation 0.3s ease-in-out;

	span {
		white-space: nowrap;
		display: inline-block;
	}

	&:hover {
		span {
			color: var(--color-primary-light-2);
		}
	}
	&__text {
		flex-direction: column;
		justify-content: center;
		align-items: center;
	}
	&__title {
		font-size: 18px;

	}
	&__subtitle {
		font-size: 8px;
	}

	&-medium-img {
		width: 40px;
		margin-right: 5px;
	}
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
