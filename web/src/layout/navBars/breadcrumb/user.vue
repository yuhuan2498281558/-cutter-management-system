<template>
	<div class="layout-navbars-breadcrumb-user pr15" :style="{ flex: layoutUserFlexNum }">
		<el-dropdown :show-timeout="70" :hide-timeout="50" trigger="click" @command="onComponentSizeChange">
			<div class="layout-navbars-breadcrumb-user-icon">
				<i class="iconfont icon-ziti" :title="$t('message.user.title0')"></i>
			</div>
			<template #dropdown>
				<el-dropdown-menu>
					<el-dropdown-item command="large" :disabled="state.disabledSize === 'large'">{{ $t('message.user.dropdownLarge') }}</el-dropdown-item>
					<el-dropdown-item command="default" :disabled="state.disabledSize === 'default'">{{ $t('message.user.dropdownDefault') }}</el-dropdown-item>
					<el-dropdown-item command="small" :disabled="state.disabledSize === 'small'">{{ $t('message.user.dropdownSmall') }}</el-dropdown-item>
				</el-dropdown-menu>
			</template>
		</el-dropdown>
		<el-dropdown :show-timeout="70" :hide-timeout="50" trigger="click" @command="onLanguageChange">
			<div class="layout-navbars-breadcrumb-user-icon">
				<i
					class="iconfont"
					:class="state.disabledI18n === 'en' ? 'icon-fuhao-yingwen' : 'icon-fuhao-zhongwen'"
					:title="$t('message.user.title1')"
				></i>
			</div>
			<template #dropdown>
				<el-dropdown-menu>
					<el-dropdown-item command="zh-cn" :disabled="state.disabledI18n === 'zh-cn'">简体中文</el-dropdown-item>
					<el-dropdown-item command="en" :disabled="state.disabledI18n === 'en'">English</el-dropdown-item>
					<el-dropdown-item command="zh-tw" :disabled="state.disabledI18n === 'zh-tw'">繁體中文</el-dropdown-item>
				</el-dropdown-menu>
			</template>
		</el-dropdown>
		<span class="layout-navbars-breadcrumb-user-divider"></span>
		<div class="layout-navbars-breadcrumb-user-icon" @click="onSearchClick">
			<el-icon :title="$t('message.user.title2')">
				<ele-Search />
			</el-icon>
		</div>
		<div class="layout-navbars-breadcrumb-user-icon" @click="onLayoutSetingClick">
			<i class="icon-skin iconfont" :title="$t('message.user.title3')"></i>
		</div>
		<div class="layout-navbars-breadcrumb-user-icon">
			<el-popover placement="bottom" trigger="click" transition="el-zoom-in-top" :width="300" :persistent="false">
				<template #reference>
					<el-badge class="layout-navbars-breadcrumb-user-news" :value="messageCenter.unread" :hidden="messageCenter.unread === 0">
						<el-icon :title="$t('message.user.title4')">
							<ele-Bell />
						</el-icon>
					</el-badge>
				</template>
				<template #default>
					<UserNews />
				</template>
			</el-popover>
		</div>
		<div class="layout-navbars-breadcrumb-user-icon" @click="onScreenfullClick">
			<i
				class="iconfont"
				:title="state.isScreenfull ? $t('message.user.title6') : $t('message.user.title5')"
				:class="!state.isScreenfull ? 'icon-fullscreen' : 'icon-tuichuquanping'"
			></i>
		</div>
		<!-- 侧边栏布局的头像和用户菜单在侧栏底部（layout/component/asideUser.vue），顶栏不再显示 -->
		<template v-if="themeConfig.layout !== 'defaults'">
    <div class="ml10">
      <span v-if="!isSocketOpen">
        <el-popconfirm
          width="250"
          ref="onlinePopoverRef"
          :confirm-button-text="$t('message.user.retry')"
          :icon="InfoFilled"
          trigger="hover"
          icon-color="#626AEF"
          :title="$t('message.user.onlinePrompt')"
          @confirm="onlineConfirmEvent"
        >
          <template #reference>
            <el-badge is-dot class="item" :class="{'online-status': isSocketOpen,'online-down':!isSocketOpen}">
              <img :src="userInfos.avatar || headerImage" class="layout-navbars-breadcrumb-user-link-photo mr5" />
            </el-badge>
          </template>
        </el-popconfirm>
      </span>
    </div>
		<UserDropdown :show-timeout="70" :hide-timeout="50">
			<span class="layout-navbars-breadcrumb-user-link">
        <span v-if="isSocketOpen">
          <el-badge is-dot class="item" :class="{'online-status': isSocketOpen,'online-down':!isSocketOpen}">
            <img :src="userInfos.avatar || headerImage" class="layout-navbars-breadcrumb-user-link-photo mr5" />
          </el-badge>
        </span>
				{{ userInfos.username === '' ? 'common' : userInfos.username }}
				<el-icon class="el-icon--right">
					<ele-ArrowDown />
				</el-icon>
			</span>
		</UserDropdown>
		</template>
		<Search ref="searchRef" />
	</div>
</template>

<script setup lang="ts" name="layoutBreadcrumbUser">
import { defineAsyncComponent, ref, computed, reactive, onMounted } from 'vue';
import { ElMessage } from 'element-plus';
import screenfull from 'screenfull';
import { useI18n } from 'vue-i18n';
import { storeToRefs } from 'pinia';
import { useUserInfo } from '/@/stores/userInfo';
import { useThemeConfig } from '/@/stores/themeConfig';
import other from '/@/utils/other';
import mittBus from '/@/utils/mitt';
import { Local } from '/@/utils/storage';
import headerImage from '/@/assets/img/headerImage.png';
import { InfoFilled } from '@element-plus/icons-vue'
import { useOnlineReconnect } from '/@/layout/navBars/breadcrumb/useOnlineReconnect';
// 引入组件
const UserNews = defineAsyncComponent(() => import('/@/layout/navBars/breadcrumb/userNews.vue'));
const Search = defineAsyncComponent(() => import('/@/layout/navBars/breadcrumb/search.vue'));
const UserDropdown = defineAsyncComponent(() => import('/@/layout/navBars/breadcrumb/userDropdown.vue'));

// 定义变量内容
const { locale } = useI18n();
const stores = useUserInfo();
const storesThemeConfig = useThemeConfig();
const { userInfos } = storeToRefs(stores);
const { themeConfig } = storeToRefs(storesThemeConfig);
const searchRef = ref();
const state = reactive({
	isScreenfull: false,
	disabledI18n: 'zh-cn',
	disabledSize: 'large',
});

// 设置分割样式
const layoutUserFlexNum = computed(() => {
	let num: string | number = '';
	const { layout, isClassicSplitMenu } = themeConfig.value;
	const layoutArr: string[] = ['defaults', 'columns'];
	if (layoutArr.includes(layout) || (layout === 'classic' && !isClassicSplitMenu)) num = '1';
	else num = '';
	return num;
});

// websocket状态
const { isSocketOpen, onlinePopoverRef, onlineConfirmEvent } = useOnlineReconnect();
// 全屏点击时
const onScreenfullClick = () => {
	if (!screenfull.isEnabled) {
		ElMessage.warning('暂不不支持全屏');
		return false;
	}
	screenfull.toggle();
	screenfull.on('change', () => {
		if (screenfull.isFullscreen) state.isScreenfull = true;
		else state.isScreenfull = false;
	});
};
// 布局配置 icon 点击时
const onLayoutSetingClick = () => {
	mittBus.emit('openSetingsDrawer');
};
// 菜单搜索点击
const onSearchClick = () => {
	searchRef.value.openSearch();
};
// 组件大小改变
const onComponentSizeChange = (size: string) => {
	Local.remove('themeConfig');
	themeConfig.value.globalComponentSize = size;
	Local.set('themeConfig', themeConfig.value);
	initI18nOrSize('globalComponentSize', 'disabledSize');
	window.location.reload();
};
// 语言切换
const onLanguageChange = (lang: string) => {
	Local.remove('themeConfig');
	themeConfig.value.globalI18n = lang;
	Local.set('themeConfig', themeConfig.value);
	locale.value = lang;
	other.useTitle();
	initI18nOrSize('globalI18n', 'disabledI18n');
};
// 初始化组件大小/i18n
const initI18nOrSize = (value: string, attr: string) => {
	state[attr] = Local.get('themeConfig')[value];
};
// 页面加载时
onMounted(() => {
	if (Local.get('themeConfig')) {
		initI18nOrSize('globalComponentSize', 'disabledSize');
		initI18nOrSize('globalI18n', 'disabledI18n');
	}
});

//消息中心的未读数量
import { messageCenterStore } from '/@/stores/messageCenter';
const messageCenter = messageCenterStore();
</script>

<style scoped lang="scss">
.layout-navbars-breadcrumb-user {
	display: flex;
	align-items: center;
	justify-content: flex-end;
	gap: 2px;
	&-link {
		height: 100%;
		display: flex;
		align-items: center;
		white-space: nowrap;
		&-photo {
			width: 25px;
			height: 25px;
			border-radius: 100%;
		}
	}
	// 工具图标：34px 圆角图标按钮，透明底，悬停浅底 + 正文色
	&-icon {
		width: 34px;
		height: 34px;
		flex: none;
		display: flex;
		align-items: center;
		justify-content: center;
		border-radius: var(--dv-radius);
		cursor: pointer;
		color: var(--next-bg-topBarColor);
		transition: background-color 0.15s, color 0.15s;
		&:hover {
			background: var(--dv-hover);
			color: var(--dv-text);
		}
	}
	// 图标分组的竖线
	&-divider {
		width: 1px;
		height: 18px;
		margin: 0 6px;
		flex: none;
		background: var(--dv-border);
	}
	// 通知未读数：危险色，外圈一道面板色描边
	:deep(.layout-navbars-breadcrumb-user-news .el-badge__content) {
		border: none;
		background-color: var(--dv-danger);
		box-shadow: 0 0 0 2px var(--dv-surface);
	}
	:deep(.el-dropdown) {
		color: var(--next-bg-topBarColor);
	}
	:deep(.el-badge) {
		height: 40px;
		line-height: 40px;
		display: flex;
		align-items: center;
	}
	:deep(.el-badge__content.is-fixed) {
		top: 12px;
	}
  .online-status{
    cursor: pointer;
    :deep(.el-badge__content.is-fixed) {
      top: 30px;
      font-size: 14px;
      left: 5px;
      height: 12px;
      width: 12px;
      padding: 0;
      background-color: var(--dv-success);
    }
  }
  .online-down{
    cursor: pointer;
    :deep(.el-badge__content.is-fixed) {
      top: 30px;
      font-size: 14px;
      left: 5px;
      height: 12px;
      width: 12px;
      padding: 0;
      // 离线用灰点（信息色已改成蓝色）
      background-color: var(--dv-text-muted);
    }
  }
}
</style>
