<template>
  <div class="mobile-login">
    <div class="login-panel">
      <div class="brand">换刀录入</div>
      <div class="subtitle">现场移动端</div>
      <van-form @submit="onSubmit">
        <van-cell-group inset>
          <van-field v-model="form.username" name="username" label="账号" placeholder="请输入账号" :rules="[{ required: true, message: '请输入账号' }]" />
          <van-field v-model="form.password" type="password" name="password" label="密码" placeholder="请输入密码" :rules="[{ required: true, message: '请输入密码' }]" />
          <van-field v-model="form.captcha" name="captcha" label="验证码" maxlength="4" placeholder="请输入验证码" :rules="[{ required: true, message: '请输入验证码' }]">
            <template #button>
              <img class="captcha-img" :src="form.captchaImgBase" alt="验证码" @click="refreshCaptcha" />
            </template>
          </van-field>
        </van-cell-group>
        <div class="actions">
          <van-button block type="primary" native-type="submit" :loading="loading">登录</van-button>
        </div>
      </van-form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue';
import { useRouter, useRoute } from 'vue-router';
import { showToast } from 'vant';
import { Md5 } from 'ts-md5';
import { mobileLogin, getMobileMe, getCaptcha } from './api';
import { Session } from '/@/utils/storage';

const router = useRouter();
const route = useRoute();
const loading = ref(false);
const form = reactive({ username: '', password: '', captcha: '', captchaKey: '', captchaImgBase: '' });

async function refreshCaptcha() {
  form.captcha = '';
  const res: any = await getCaptcha();
  form.captchaImgBase = res.data.image_base;
  form.captchaKey = res.data.key;
}

async function onSubmit() {
  loading.value = true;
  try {
    const res: any = await mobileLogin({
      username: form.username,
      password: Md5.hashStr(form.password),
      captcha: form.captcha,
      captchaKey: form.captchaKey,
    });
    Session.set('token', res.data.access);
    const me: any = await getMobileMe();
    if (!me.data?.has_mobile_access) {
      Session.clear();
      showToast('当前账号没有移动端录入权限');
      return;
    }
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '';
    // 只允许回到移动端页面，避免外部/后台路径把登录流程带进另一套路由守卫。
    const target = redirect.startsWith('/mobile/') && redirect !== '/mobile/login' ? redirect : '/mobile/tasks';
    await router.replace(target);
  } catch (e: any) {
    Session.clear();
    refreshCaptcha();
    showToast(e?.response?.data?.detail || e?.msg || e?.message || '移动端权限校验失败');
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  refreshCaptcha();
});
</script>

<style scoped lang="scss">
.mobile-login {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f4f7f8;
  padding: 24px 16px;
}
.login-panel {
  width: 100%;
  max-width: 420px;
}
.brand {
  font-size: 28px;
  font-weight: 700;
  color: #17233d;
  margin-bottom: 6px;
}
.subtitle {
  color: #5d6b78;
  margin-bottom: 24px;
}
.actions {
  margin: 22px 16px 0;
}
.captcha-img {
  display: block;
  width: 96px;
  height: 34px;
  object-fit: contain;
}
</style>
