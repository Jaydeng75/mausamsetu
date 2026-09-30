'use client';
import {useEffect,useRef} from 'react';
import * as echarts from 'echarts/core';
import {LineChart,BarChart,ScatterChart} from 'echarts/charts';
import {GridComponent,TooltipComponent,LegendComponent,MarkLineComponent,DataZoomComponent} from 'echarts/components';
import {CanvasRenderer} from 'echarts/renderers';
echarts.use([LineChart,BarChart,ScatterChart,GridComponent,TooltipComponent,LegendComponent,MarkLineComponent,DataZoomComponent,CanvasRenderer]);
export default function Chart({option,height=250,label}:{option:echarts.EChartsCoreOption;height?:number;label:string}){const el=useRef<HTMLDivElement>(null),instance=useRef<echarts.ECharts|null>(null);useEffect(()=>{if(!el.current)return;instance.current=echarts.init(el.current);const ro=new ResizeObserver(()=>instance.current?.resize());ro.observe(el.current);return()=>{ro.disconnect();instance.current?.dispose();};},[]);useEffect(()=>{instance.current?.setOption({backgroundColor:'transparent',textStyle:{fontFamily:'Arial',color:'#90a9bd',fontSize:11},grid:{top:25,bottom:34,left:43,right:18},tooltip:{trigger:'axis',backgroundColor:'#142638',borderColor:'#365065',textStyle:{color:'#e5f3fc'}},...option},true);},[option]);return <div ref={el} role="img" aria-label={label} style={{height,width:'100%'}}/>;}
