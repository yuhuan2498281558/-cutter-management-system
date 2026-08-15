<template>
	<div class="login-page">
		<img :src="loginBg" class="login-page__background" alt="" aria-hidden="true" fetchpriority="high" />
		<div class="login-page__scrim" aria-hidden="true"></div>

		<main class="login-page__content">
			<section class="login-panel" aria-labelledby="login-title">
				<header class="login-panel__header">
					<span class="login-panel__accent" aria-hidden="true"></span>
					<div>
						<h1 id="login-title">刀具管理系统</h1>
						<p>盾构刀具全生命周期管理平台</p>
					</div>
				</header>

				<div class="login-panel__divider"></div>
				<h2>{{ userInfos.pwd_change_count === 0 ? '初次登录修改密码' : '账号登录' }}</h2>
				<p v-if="userInfos.pwd_change_count !== 0" class="login-panel__hint">请输入系统账号完成身份验证</p>

				<div class="login-panel__form">
					<el-tabs v-model="state.tabsActiveName">
						<el-tab-pane v-if="userInfos.pwd_change_count === 0" :label="$t('message.label.changePwd')" name="changePwd">
							<ChangePwd />
						</el-tab-pane>
						<el-tab-pane v-else :label="$t('message.label.one1')" name="account">
							<Account />
						</el-tab-pane>
					</el-tabs>
				</div>

				<footer class="login-panel__footer">
					<span>数据驱动</span>
					<span>过程可追溯</span>
					<span>安全可控</span>
				</footer>
			</section>
		</main>

		<footer class="login-authorization">
			<p>Copyright © {{ getSystemConfig['login.copyright'] || '刀具管理系统 版权所有' }}</p>
			<p class="login-authorization__links">
				<a v-if="getSystemConfig['login.keep_record']" href="https://beian.miit.gov.cn" target="_blank" rel="noreferrer">
					{{ getSystemConfig['login.keep_record'] }}
				</a>
				<a v-if="getSystemConfig['login.help_url']" :href="getSystemConfig['login.help_url']" target="_blank" rel="noreferrer">帮助</a>
				<a v-if="getSystemConfig['login.privacy_url']" :href="getBaseURL(getSystemConfig['login.privacy_url'])">隐私</a>
				<a v-if="getSystemConfig['login.clause_url']" :href="getBaseURL(getSystemConfig['login.clause_url'])">条款</a>
			</p>
		</footer>
	</div>
</template>

<script setup lang="ts" name="loginIndex">
import { computed, defineAsyncComponent, onMounted, reactive, watch } from 'vue';
import { storeToRefs } from 'pinia';
import { NextLoading } from '/@/utils/loading';
import { SystemConfigStore } from '/@/stores/systemConfig';
import { getBaseURL } from '/@/utils/baseUrl';
import { useUserInfo } from '/@/stores/userInfo';

const Account = defineAsyncComponent(() => import('/@/views/system/login/component/account.vue'));
const ChangePwd = defineAsyncComponent(() => import('/@/views/system/login/component/changePwd.vue'));
const { userInfos } = storeToRefs(useUserInfo());
const systemConfigStore = SystemConfigStore();
const { systemConfig } = storeToRefs(systemConfigStore);

const state = reactive({
	tabsActiveName: 'account',
});

const getSystemConfig = computed(() => systemConfig.value);
const loginBg = '/login-cutterhead-placeholder.svg';

watch(
	() => userInfos.value.pwd_change_count,
	(value) => {
		state.tabsActiveName = value === 0 ? 'changePwd' : 'account';
	},
	{ immediate: true }
);

onMounted(() => {
	NextLoading.done();
});
</script>

<style scoped lang="scss">
.login-page {
	position: relative;
	isolation: isolate;
	min-height: 100dvh;
	overflow-x: hidden;
	overflow-y: auto;
	background: #14181c;
	font-family: "Microsoft YaHei", "PingFang SC", Arial, sans-serif;
	color: #eef2f4;
}

.login-page__background {
	position: fixed;
	top: 0;
	right: 0;
	bottom: 0;
	z-index: -3;
	display: block;
	width: auto;
	height: 100%;
	max-width: none;
	object-fit: contain;
	object-position: right center;
	filter: brightness(0.9) saturate(0.92) contrast(1.04);
}

.login-page__scrim {
	position: fixed;
	inset: 0;
	z-index: -2;
	background:
		linear-gradient(90deg, rgba(7, 10, 13, 0.84) 0%, rgba(7, 10, 13, 0.74) 22%, rgba(7, 10, 13, 0.42) 38%, rgba(7, 10, 13, 0.08) 57%, rgba(7, 10, 13, 0.02) 76%, rgba(7, 10, 13, 0.2) 100%),
		linear-gradient(0deg, rgba(7, 9, 11, 0.34) 0%, rgba(7, 9, 11, 0) 24%, rgba(7, 9, 11, 0) 76%, rgba(7, 9, 11, 0.16) 100%);
	pointer-events: none;
}

.login-page__content {
	min-height: 100dvh;
	box-sizing: border-box;
	display: flex;
	align-items: center;
	padding: clamp(28px, 5vh, 58px) clamp(24px, 7vw, 118px) 84px;
}

.login-panel {
	width: min(100%, 442px);
	box-sizing: border-box;
	padding: 42px 44px 34px;
	border: 1px solid rgba(177, 190, 199, 0.3);
	border-radius: 14px;
	background: rgba(13, 17, 21, 0.91);
	box-shadow: 0 24px 70px rgba(4, 7, 9, 0.3), inset 0 1px 0 rgba(255, 255, 255, 0.04);
	backdrop-filter: blur(10px);
	-webkit-backdrop-filter: blur(10px);
}

.login-panel__header {
	display: flex;
	align-items: stretch;
	gap: 22px;
}

.login-panel__accent {
	flex: 0 0 7px;
	border-radius: 7px;
	background: #d5332f;
}

.login-panel h1 {
	margin: 0;
	font-size: 31px;
	font-weight: 700;
	line-height: 1.25;
	letter-spacing: 0;
	color: #f4f6f7;
}

.login-panel__header p {
	margin: 7px 0 0;
	font-size: 13px;
	line-height: 1.6;
	color: #aeb8bf;
}

.login-panel__divider {
	height: 1px;
	margin: 25px 0 22px;
	background: rgba(177, 190, 199, 0.24);
}

.login-panel h2 {
	margin: 0;
	font-size: 17px;
	font-weight: 600;
	line-height: 1.4;
	color: #e5eaed;
}

.login-panel__hint {
	margin: 6px 0 0;
	font-size: 12px;
	line-height: 1.6;
	color: #8e9ba4;
}

.login-panel__form {
	margin-top: 20px;
}

.login-panel :deep(.el-tabs__header) {
	display: none;
}

.login-panel :deep(.el-form-item) {
	margin-bottom: 17px;
}

.login-panel :deep(.el-form-item__label) {
	padding-bottom: 8px;
	font-size: 13px;
	font-weight: 600;
	line-height: 1;
	color: #d7dde1;
}

.login-panel :deep(.el-input__wrapper) {
	min-height: 46px;
	padding: 0 13px;
	border-radius: 8px;
	background: #1c2328;
	box-shadow: 0 0 0 1px #53616a inset !important;
	transition: background 0.18s ease, box-shadow 0.18s ease;
}

.login-panel :deep(.el-input__wrapper:hover) {
	background: #20282e;
	box-shadow: 0 0 0 1px #71818b inset !important;
}

.login-panel :deep(.el-input__wrapper.is-focus) {
	background: #20282e;
	box-shadow: 0 0 0 1px #d5332f inset, 0 0 0 3px rgba(213, 51, 47, 0.2) !important;
}

.login-panel :deep(.el-input__inner) {
	font-size: 14px;
	color: #f0f3f4;
}

.login-panel :deep(.el-input__inner::placeholder) {
	color: #8d9aa2;
}

.login-panel :deep(input:-webkit-autofill),
.login-panel :deep(input:-webkit-autofill:hover),
.login-panel :deep(input:-webkit-autofill:focus) {
	-webkit-text-fill-color: #f0f3f4;
	caret-color: #f0f3f4;
	box-shadow: 0 0 0 1000px #1c2328 inset;
	transition: background-color 9999s ease-out 0s;
}

.login-panel :deep(.el-input__prefix),
.login-panel :deep(.el-input__suffix) {
	color: #aab5bc;
}

.login-panel :deep(.el-form-item__error) {
	padding-top: 5px;
	color: #ff807b;
}

.login-panel__footer {
	display: grid;
	grid-template-columns: repeat(3, minmax(0, 1fr));
	align-items: center;
	margin-top: 18px;
	padding-top: 20px;
	border-top: 1px solid rgba(177, 190, 199, 0.18);
	font-size: 12px;
	line-height: 1.5;
	color: #87949d;
}

.login-panel__footer span:nth-child(2) {
	text-align: center;
}

.login-panel__footer span:last-child {
	text-align: right;
}

.login-authorization {
	position: absolute;
	left: clamp(24px, 7vw, 118px);
	bottom: 24px;
	display: flex;
	align-items: center;
	gap: 18px;
	font-size: 11px;
	line-height: 1.5;
	color: #839099;
}

.login-authorization p {
	margin: 0;
	white-space: nowrap;
}

.login-authorization__links {
	display: flex;
	align-items: center;
	gap: 13px;
}

.login-authorization a {
	color: #aab4ba;
	text-decoration: none;
}

.login-authorization a:hover {
	color: #f0f3f4;
}

@media (max-width: 1180px) {
	.login-page__scrim {
		background:
			linear-gradient(90deg, rgba(7, 10, 13, 0.86) 0%, rgba(7, 10, 13, 0.68) 44%, rgba(7, 10, 13, 0.2) 78%, rgba(7, 10, 13, 0.3) 100%),
			linear-gradient(0deg, rgba(7, 9, 11, 0.38) 0%, rgba(7, 9, 11, 0) 30%, rgba(7, 9, 11, 0.18) 100%);
	}

	.login-page__content {
		padding-inline: clamp(28px, 5vw, 64px);
	}

	.login-authorization {
		left: clamp(28px, 5vw, 64px);
	}
}

@media (max-width: 900px) {
	.login-page__background {
		width: 100%;
		height: 100%;
		object-fit: cover;
		object-position: 66% center;
		filter: brightness(0.72) saturate(0.78) contrast(1.03);
	}

	.login-page__scrim {
		background: rgba(7, 10, 13, 0.64);
	}

	.login-page__content {
		justify-content: center;
		padding: 28px 18px 76px;
	}

	.login-authorization {
		left: 18px;
		right: 18px;
		bottom: 14px;
		flex-direction: column;
		gap: 2px;
		text-align: center;
	}

	.login-authorization p {
		white-space: normal;
	}

	.login-authorization__links {
		justify-content: center;
	}
}

@media (max-width: 520px) {
	.login-page__content {
		align-items: flex-start;
		min-height: auto;
		padding-top: 18px;
	}

	.login-panel {
		padding: 30px 22px 26px;
	}

	.login-panel h1 {
		font-size: 27px;
	}

	.login-panel__footer {
		font-size: 11px;
	}
}

@media (prefers-reduced-transparency: reduce) {
	.login-panel {
		background: #11161a;
		backdrop-filter: none;
		-webkit-backdrop-filter: none;
	}
}

@media (prefers-reduced-motion: reduce) {
	.login-page :deep(*) {
		transition-duration: 0.01ms !important;
		animation-duration: 0.01ms !important;
		animation-iteration-count: 1 !important;
	}
}
</style>
