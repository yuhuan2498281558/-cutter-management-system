
import { useTypes } from '@fast-crud/fast-crud'

export const ipInputFieldTyps = () =>{
const { addTypes } = useTypes()
addTypes({
  'ip_input':{ //如果与官方字段类型同名，将会覆盖官方的字段类型
     form: {
      helper:'只能输入格式为xxx.xxx.xxx.xxx的IP地址',
      rules: [{ pattern:/^(25[0-5]|2[0-4]\d|[0-1]?\d?\d)(\.(25[0-5]|2[0-4]\d|[0-1]?\d?\d)){3}$/, message: '格式如192.168.1.1或255.255.255.0'}],
      component: { name: 'el-input' }
    },
  }
})
}