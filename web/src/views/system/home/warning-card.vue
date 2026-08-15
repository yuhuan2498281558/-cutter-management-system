<template>
  <div class="warning-card">
    <div class="card-header">
      <h2>今日预警数据</h2>
    </div>
    <div class="card-body">
      <table v-if="warnings.length > 0" class="warning-table">
        <thead>
          <tr>
            <th>刀具类型</th>
            <th>损伤程度</th>
            <th>预警数值</th>
            <th>预警时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(warning, index) in warnings" :key="index">
            <td>{{ warning.sensorType }}</td>
            <td>{{ warning.monitoringPoint }}</td>
            <td :class="getSeverityClass(warning.severity)">{{ warning.severity }}</td>
            <td>{{ warning.value }}</td>
            <td>{{ warning.time }}</td>
          </tr>
        </tbody>
      </table>
      <div v-else class="no-data">暂无数据</div>
    </div>
  </div>
</template>

<script setup>
import { ref, defineProps } from 'vue';

// 定义组件接收的 props
const props = defineProps({
  warnings: {
    type: Array,
    default: () => []
  }
});

// 根据严重程度返回不同的样式类
const getSeverityClass = (severity) => {
  switch (severity) {
    case '严重':
      return 'severity-high';
    case '中等':
      return 'severity-medium';
    case '轻微':
      return 'severity-low';
    default:
      return '';
  }
};
</script>

<style scoped>
.warning-card {
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
  margin: 10px;
  width: 300px;
}

.card-header {
  background-color: #f5f5f5;
  padding: 10px;
  text-align: center;
  border-bottom: 1px solid #e0e0e0;
}

.card-header h2 {
  margin: 0;
  font-size: 18px;
}

.card-body {
  padding: 10px;
}

.warning-table {
  width: 100%;
  border-collapse: collapse;
}

.warning-table th, .warning-table td {
  border: 1px solid #e0e0e0;
  padding: 8px;
  text-align: left;
}

.warning-table th {
  background-color: #f5f5f5;
}

.no-data {
  text-align: center;
  padding: 20px;
  color: #999;
}

.severity-high {
  color: red;
}

.severity-medium {
  color: orange;
}

.severity-low {
  color: green;
}
</style>