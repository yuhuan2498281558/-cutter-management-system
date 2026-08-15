// 创建一个readonly的方法,参考官方http://fast-crud.docmirror.cn/guide/advance/column-type.html#%E5%AD%97%E6%AE%B5merge%E6%8F%92%E4%BB%B6
import { useColumns, ColumnCompositionProps } from '@fast-crud/fast-crud'
import _ from 'lodash';

//配置一个导出来的名称，等一下别的地方可以导入使用import { readonlyRegisterMergeColumnPlugin } from './custom/customMethod';
export const readonlyRegisterMergeColumnPlugin = () =>{
const { registerMergeColumnPlugin } = useColumns();
registerMergeColumnPlugin({
    name: 'readonly-plugin',
    order: 1,
    handle: (columnProps: ColumnCompositionProps={},crudOptions:any={}) => {
        // 你可以在此处做你自己的处理
        // 比如你可以定义一个readonly的公共属性，处理该字段只读，不能编辑
        if (columnProps.readonly) {
            // 合并column配置
            _.merge(columnProps, {
                form: {show: false},
                viewForm: {show: true},
            });
        }
        return columnProps;
    }
});
}