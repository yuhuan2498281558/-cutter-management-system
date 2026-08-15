import { useTypes, useColumns, ColumnCompositionProps} from '@fast-crud/fast-crud'
import _ from 'lodash';


//配置一个导出来的名称，等一下别的地方可以导入使用import { readonlyRegisterMergeColumnPlugin } from './custom/customMethod';
export const customDateRegisterMergeColumnPlugin = () =>{

    // 注释编号:django-vue3-admin__customDate260113:代码开始行
    // 功能说明:这时对date字段类型的属性进行定制处理
    const { getType } = useTypes()
    const selectType = getType('date')  //这里直接匹配到date类型
    // 如下对于column及form的字段属性的进行了处理
    selectType.column.component.color='auto'
    selectType.column.component.format='YYYY-MM-DD'
    selectType.column.component.valueFormat='YYYY-MM-DD'
    selectType.form.component.format='YYYY-MM-DD'
    selectType.form.component.valueFormat='YYYY-MM-DD'
    // 注释编号:django-vue3-admin__customDate260113:代码结束行



    // 注释编号:django-vue3-admin__customDate160013:代码开始行
    // 功能说明:这里是对date类型字段中valueResolve方法的定制处理
    const { registerMergeColumnPlugin } = useColumns();
    registerMergeColumnPlugin({
        name: 'customDate-Plugin',
        order: 1,
        handle: (columnProps: ColumnCompositionProps={}) => {
            // 你可以在此处做你自己的处理
            // 比如你可以定义一个readonly的公共属性，处理该字段只读，不能编辑
            if(columnProps.type == "date"){
                _.merge(columnProps, {
                    form: {
                        valueBuilder(context: any){//加载前处理转化
                            //如果配置在form下，则表示将行数据的值转化为表单组件所需要的值
                            //在点击编辑按钮之后，弹出表单对话框之前执行转化。
                            // 也就是说在被始化form的时候,就把日期格式给转化为正确的格式了.
                            let value = context.form[columnProps.key]
                            if (value !== null && typeof(value) !== 'string' && typeof(value) === 'object') {
                                context.form[columnProps.key] = value.format('YYYY-MM-DD');
                            }

                        },
                        valueResolve(context: any){//提交前再处理转化
                            //与builder相反，提交表单时，需要将value值转换为后台所需要的格式提交给后台
                            let value = context.form[columnProps.key]
                            //这里要判断value是非空,是object对象及不是字符串(新增的时候传进来就是字符串而非对象)
                            if (value !== null && typeof(value) !== 'string' && typeof(value) === 'object') {
                                context.form[columnProps.key] = value.format('YYYY-MM-DD');
                            }
                        },

                    },

                });
        }

            return columnProps;
        }
    });
    // 注释编号:django-vue3-admin__customDate160013:代码结束行



    }
