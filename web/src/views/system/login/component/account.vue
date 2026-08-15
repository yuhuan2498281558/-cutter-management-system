<template>
	<el-form ref="formRef" size="large" class="login-content-form" label-position="top" :model="state.ruleForm" :rules="rules" @keyup.enter="loginClick">
		<el-form-item class="login-animation1" label="账号" prop="username">
			<el-input type="text" placeholder="请输入账号" v-model="ruleForm.username" clearable autocomplete="username">
				<template #prefix>
					<el-icon class="el-input__icon"><ele-User /></el-icon>
				</template>
			</el-input>
		</el-form-item>
		<el-form-item class="login-animation2" label="密码" prop="password">
			<el-input :type="isShowPassword ? 'text' : 'password'" placeholder="请输入密码" v-model="ruleForm.password" autocomplete="current-password">
				<template #prefix>
					<el-icon class="el-input__icon"><ele-Unlock /></el-icon>
				</template>
				<template #suffix>
					<i class="iconfont el-input__icon login-content-password"
						:class="isShowPassword ? 'icon-yincangmima' : 'icon-xianshimima'"
						@click="isShowPassword = !isShowPassword">
					</i>
				</template>
			</el-input>
		</el-form-item>
		<el-form-item class="login-animation3" v-if="isShowCaptcha" label="验证码" prop="captcha">
			<div class="login-captcha-row">
				<el-input type="text" maxlength="4" placeholder="请输入验证码" v-model="ruleForm.captcha" clearable autocomplete="off">
					<template #prefix>
						<el-icon class="el-input__icon"><ele-Position /></el-icon>
					</template>
				</el-input>
				<el-button class="login-content-captcha" native-type="button" title="刷新验证码" aria-label="刷新验证码" @click="refreshCaptcha">
					<el-image :src="ruleForm.captchaImgBase" fit="fill" />
				</el-button>
			</div>
			<span class="login-captcha-help">点击图片刷新验证码</span>
		</el-form-item>
		<div class="login-options login-animation4">
			<el-checkbox v-model="state.rememberUsername">记住账号</el-checkbox>
			<span>忘记密码请联系管理员</span>
		</div>
		<el-form-item class="login-animation4 login-submit-item">
			<el-button type="primary" class="login-content-submit" @click="loginClick" :loading="loading.signIn">
				<span>{{ $t('message.account.accountBtnText') }}</span>
			</el-button>
		</el-form-item>
	</el-form>
</template>

<script lang="ts">
import { toRefs, reactive, defineComponent, computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage, FormRules } from 'element-plus';
import { useI18n } from 'vue-i18n';
import Cookies from 'js-cookie';
import { storeToRefs } from 'pinia';
import { useThemeConfig } from '/@/stores/themeConfig';
import { initFrontEndControlRoutes } from '/@/router/frontEnd';
import { Session } from '/@/utils/storage';
import { formatAxis } from '/@/utils/formatTime';
import { NextLoading } from '/@/utils/loading';
import * as loginApi from '/@/views/system/login/api';
import { useUserInfo } from '/@/stores/userInfo';
import { DictionaryStore } from '/@/stores/dictionary';
import { SystemConfigStore } from '/@/stores/systemConfig';
import { Md5 } from 'ts-md5';
import { errorMessage } from '/@/utils/message';

export default defineComponent({
	name: 'loginAccount',
	setup() {
		const rememberedUsernameKey = 'login.remembered_username';
		const rememberedUsername = localStorage.getItem(rememberedUsernameKey) || '';
		const { t } = useI18n();
		const storesThemeConfig = useThemeConfig();
		const { themeConfig } = storeToRefs(storesThemeConfig);
		const route = useRoute();
		const router = useRouter();
		const systemConfigStore = SystemConfigStore();
		const state = reactive({
			isShowPassword: false,
			rememberUsername: Boolean(rememberedUsername),
			ruleForm: {
				username: rememberedUsername,
				password: '',
				captcha: '',
				captchaKey: '',
				captchaImgBase: '',
			},
			loading: {
				signIn: false,
			},
		});
		const rules = reactive<FormRules>({
			username: [
				{ required: true, message: '请填写账号', trigger: 'blur' },
			],
			password: [
				{
					required: true,
					message: '请填写密码',
					trigger: 'blur',
				},
			],
			captcha: [
				{
					required: true,
					message: '请填写验证码',
					trigger: 'blur',
				},
			],
		})
		const formRef = ref();
		// 时间获取
		const currentTime = computed(() => {
			return formatAxis(new Date());
		});
		// 是否关闭验证码
		const isShowCaptcha = computed(() => {
			const captchaState = systemConfigStore.systemConfig['base.captcha_state'];
			return captchaState === undefined ? true : captchaState;
		});

		const getCaptcha = async () => {
			loginApi.getCaptcha().then((ret: any) => {
				state.ruleForm.captchaImgBase = ret.data.image_base;
				state.ruleForm.captchaKey = ret.data.key;
			});
		};
		const refreshCaptcha = async () => {
      state.ruleForm.captcha=''
			loginApi.getCaptcha().then((ret: any) => {
				state.ruleForm.captchaImgBase = ret.data.image_base;
				state.ruleForm.captchaKey = ret.data.key;
			});
		};
		const loginClick = async () => {
			if (!formRef.value) return
			await formRef.value.validate((valid: any) => {
				if (valid) {
					state.loading.signIn = true;
					loginApi.login({ ...state.ruleForm, password: Md5.hashStr(state.ruleForm.password) }).then(async (res: any) => {
						if (res.code === 2000) {
							if (state.rememberUsername) {
								localStorage.setItem(rememberedUsernameKey, state.ruleForm.username);
							} else {
								localStorage.removeItem(rememberedUsernameKey);
							}
							Session.set('token', res.data.access);
							Cookies.set('username', res.data.name);
							if (!themeConfig.value.isRequestRoutes) {
								// 前端控制路由，2、请注意执行顺序
								initFrontEndControlRoutes();
								loginSuccess();
							} else {
								// 后端动态路由由全局路由守卫统一初始化，避免这里和守卫重复请求。
								await loginSuccess();
							}
						}
					}).catch(() => {
            // 登录错误之后，刷新验证码
            refreshCaptcha();
					}).finally(() => {
						state.loading.signIn = false;
          });
				} else {
					errorMessage("请填写登录信息")
				}
			})

		};
		const getUserInfo = () => {
			useUserInfo().setUserInfos();
		};


		// 登录成功后的跳转
		const loginSuccess = async () => {
			// 前端控制路由需要在跳转前加载基础数据；后端控制路由由守卫统一加载。
			if (!themeConfig.value.isRequestRoutes) {
				getUserInfo();
				DictionaryStore().getSystemDictionarys();
			}

			// 初始化登录成功时间问候语
			let currentTimeInfo = currentTime.value;

			// 等待路由完全加载后再跳转
			await new Promise(resolve => setTimeout(resolve, 100));

			// 登录成功，跳到转首页
			// 如果是复制粘贴的路径，非首页/登录页，那么登录成功后重定向到对应的路径中
			if (route.query?.redirect) {
				router.push({
					path: <string>route.query?.redirect,
					query: Object.keys(<string>route.query?.params).length > 0 ? JSON.parse(<string>route.query?.params) : '',
				});
			} else {
				router.push('/');
			}
			// 登录成功提示
			// 关闭 loading
			state.loading.signIn = false;
			const signInText = t('message.signInText');
			ElMessage.success(`${currentTimeInfo}，${signInText}`);
			// 添加 loading，防止第一次进入界面时出现短暂空白
			NextLoading.start();
		};
		onMounted(() => {
			getCaptcha();
			//获取系统配置
			systemConfigStore.getSystemConfigs();
		});


		return {
			refreshCaptcha,
			loginClick,
			loginSuccess,
			isShowCaptcha,
			state,
			formRef,
			rules,
			...toRefs(state),
		};
	},
});
</script>

<style scoped lang="scss">
.login-content-form {
	margin-top: 0;

	@for $i from 1 through 4 {
		.login-animation#{$i} {
			opacity: 0;
			animation-name: error-num;
			animation-duration: 0.5s;
			animation-fill-mode: forwards;
			animation-delay: calc($i/10) + s;
		}
	}

	.login-captcha-row {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 118px;
		gap: 12px;
		width: 100%;
	}

	.login-captcha-help {
		display: block;
		width: 118px;
		margin: 6px 0 0 auto;
		text-align: center;
		font-size: 11px;
		line-height: 1.4;
		color: #87949d;
	}

	.login-content-password {
		display: inline-block;
		width: 20px;
		cursor: pointer;

		&:hover {
			color: #909399;
		}
	}

	.login-content-captcha {
		width: 100%;
		height: 46px;
		padding: 0;
		border: 1px solid #53616a;
		border-radius: 8px;
		background: #293137;
		overflow: hidden;
		font-weight: bold;
		letter-spacing: 5px;

		:deep(.el-image) {
			width: 100%;
			height: 100%;
		}

		&:hover,
		&:focus-visible {
			border-color: #8a999f;
			background: #30393f;
		}
	}

	.login-options {
		display: grid;
		grid-template-columns: max-content minmax(0, 1fr);
		align-items: center;
		column-gap: 16px;
		margin: 2px 0 18px;
		font-size: 12px;
		line-height: 1.4;
		color: #9da9b0;

		> span {
			text-align: right;
			white-space: nowrap;
		}

		:deep(.el-checkbox) {
			height: auto;
			color: #c7d0d5;
		}

		:deep(.el-checkbox__inner) {
			border-color: #697780;
			background: #1c2328;
		}

		:deep(.el-checkbox__input.is-checked .el-checkbox__inner) {
			border-color: #d5332f;
			background: #d5332f;
		}

		:deep(.el-checkbox__input.is-checked + .el-checkbox__label) {
			color: #e3e8eb;
		}

		:deep(.el-checkbox__label) {
			padding-left: 7px;
			font-size: 12px;
			line-height: 1.4;
		}
	}

	.login-submit-item {
		margin-bottom: 0;
	}

	.login-content-submit {
		width: 100%;
		height: 48px;
		margin-top: 0;
		border: 0;
		border-radius: 8px;
		background: #d5332f;
		box-shadow: 0 9px 20px rgba(126, 25, 22, 0.28);
		font-weight: 700;
		letter-spacing: 4px;
		transition: background 0.18s ease, transform 0.18s ease, box-shadow 0.18s ease;

		&:hover,
		&:focus-visible {
			background: #bd2b28;
			box-shadow: 0 11px 24px rgba(126, 25, 22, 0.34);
		}

		&:active {
			transform: translateY(1px);
		}
	}
}

@media (max-width: 420px) {
	.login-content-form {
		.login-captcha-row {
			grid-template-columns: minmax(0, 1fr) 104px;
			gap: 8px;
		}

		.login-captcha-help {
			width: 104px;
		}
	}
}
</style>
