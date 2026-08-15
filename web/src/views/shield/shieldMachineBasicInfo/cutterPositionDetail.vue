<template>
  <div class="cutter-position-detail-page">
    <div class="page-header">
      <el-button @click="goBack" type="default">
        <el-icon><ArrowLeft /></el-icon>
        返回
      </el-button>
      <h2>刀位信息管理</h2>
    </div>
    <CutterPositionDetail
      v-if="shieldMachine"
      :shield-machine="shieldMachine"
    />
  </div>
</template>

<script lang="ts" setup name="CutterPositionDetailPage">
import { ref, onMounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ArrowLeft } from '@element-plus/icons-vue';
import CutterPositionDetail from './components/CutterPositionDetail.vue';

const route = useRoute();
const router = useRouter();

const shieldMachine = ref<any>(null);

const goBack = () => {
  router.back();
};

onMounted(() => {
  // 从路由参数获取盾构机信息
  const id = route.params.id;
  const shield_model_id = route.query.shield_model_id;
  const shield_model = route.query.shield_model;

  shieldMachine.value = {
    id,
    shield_model_id,
    shield_model
  };
});
</script>

<style scoped>
.cutter-position-detail-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: #f5f5f5;
}

.page-header {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 16px 24px;
  background: #fff;
  border-bottom: 1px solid #e0e0e0;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
}

.page-header h2 {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: #333;
}
</style>
