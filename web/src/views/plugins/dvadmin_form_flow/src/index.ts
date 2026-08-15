// ����������
import DVAFormDesigner from './components/DVAFormDesigner.vue'

// ��������浽һ��������
const components = [
    DVAFormDesigner
]

// ���� install ����
const install = function (Vue) {

    if (install.installed) return
    install.installed = true
    // ��������б���ע��ȫ�����
    components.map(component => {
        Vue.component(component.name, component) //component.name �˴�ʹ�õ����vue�ļ��е� name ����
    })
}

if (typeof window !== 'undefined' && window.Vue) {
    install(window.Vue)
}

export default {
    // �����Ķ������߱�һ�� install ����
    install,
    // ����б�
    ...components
}
