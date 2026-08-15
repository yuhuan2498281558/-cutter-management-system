// 参考http://fast-crud.docmirror.cn/guide/advance/column-type.html#字段merge插件
import { useColumns, ColumnCompositionProps} from '@fast-crud/fast-crud'
import _ from 'lodash';

export const columnRegisterMergeColumnPlugin = () =>{
const { registerMergeColumnPlugin } = useColumns();
registerMergeColumnPlugin({
    name: 'column-plugin',
    order: 1,
    handle: (columnProps: ColumnCompositionProps={},crudOptions:any={}) => {

            // 合并column配置,这里单独配置了column的全局统一配置
            _.merge(columnProps, {
                column: {
                    showOverflowTooltip: true, //这里el-table的属性,在列中浮窗显示超出的内容
                    align: 'center',
                },
            });

        return columnProps;
    }
});
}