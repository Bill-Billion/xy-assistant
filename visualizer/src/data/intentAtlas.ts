import type { LucideIcon } from 'lucide-react'
import {
  AlarmClock,
  Brain,
  CalendarDays,
  Clapperboard,
  CloudSun,
  Gamepad2,
  HandHeart,
  Headset,
  HeartPulse,
  Home,
  MessageCircle,
  Pill,
  Settings,
  ShoppingBag,
  Stethoscope,
} from 'lucide-react'

export type IntentCategory = {
  id: string
  title: string
  icon: LucideIcon
  color: string
  intents: string[]
}

export const intentAtlas: IntentCategory[] = [
  {
    id: 'weather',
    title: '天气播报',
    icon: CloudSun,
    color: 'from-sky-500/30 to-sky-500/10',
    intents: ['今天天气', '明天天气', '后天天气', '特定日期天气', '农历时间'],
  },
  {
    id: 'calendar',
    title: '日程时间',
    icon: CalendarDays,
    color: 'from-amber-500/30 to-amber-500/10',
    intents: ['日期时间和万年历', '播报时间'],
  },
  {
    id: 'alarm',
    title: '提醒闹钟',
    icon: AlarmClock,
    color: 'from-brand-500/30 to-brand-500/10',
    intents: ['闹钟界面', '新增闹钟'],
  },
  {
    id: 'settings',
    title: '设备调节',
    icon: Settings,
    color: 'from-slate-500/30 to-slate-500/10',
    intents: ['小雅设置', '声音调低', '声音调高', '亮度调低', '亮度调高', '息屏'],
  },
  {
    id: 'health-monitor',
    title: '健康监测',
    icon: HeartPulse,
    color: 'from-emerald-500/30 to-emerald-500/10',
    intents: [
      '健康监测',
      '血压监测',
      '血氧监测',
      '心率监测',
      '血糖监测',
      '血脂监测',
      '体重监测',
      '体温监测',
      '血红蛋白监测',
      '尿酸监测',
      '睡眠监测',
    ],
  },
  {
    id: 'health-insight',
    title: '健康洞察',
    icon: Brain,
    color: 'from-lime-500/30 to-lime-500/10',
    intents: ['健康画像', '健康评估', '健康科普'],
  },
  {
    id: 'medication',
    title: '用药管理',
    icon: Pill,
    color: 'from-rose-500/30 to-rose-500/10',
    intents: ['用药提醒', '新建用药提醒'],
  },
  {
    id: 'doctor',
    title: '医生问诊',
    icon: Stethoscope,
    color: 'from-orange-500/30 to-orange-500/10',
    intents: ['家庭医生', '家庭医生音频通话', '家庭医生视频通话', '名医问诊', '小雅医生'],
  },
  {
    id: 'communication',
    title: '沟通互动',
    icon: MessageCircle,
    color: 'from-rose-500/30 to-rose-500/10',
    intents: ['小雅通话', '小雅音频通话', '小雅视频通话', '小雅相册', '语音陪伴或聊天'],
  },
  {
    id: 'education',
    title: '学习认知',
    icon: HandHeart,
    color: 'from-indigo-500/30 to-indigo-500/10',
    intents: ['小雅教育'],
  },
  {
    id: 'entertainment',
    title: '文娱点播',
    icon: Clapperboard,
    color: 'from-violet-500/30 to-violet-500/10',
    intents: ['娱乐', '小雅曲艺', '小雅音乐', '小雅听书', '关闭音乐', '关闭戏曲', '关闭听书'],
  },
  {
    id: 'games',
    title: '益智游戏',
    icon: Gamepad2,
    color: 'from-purple-500/30 to-purple-500/10',
    intents: ['斗地主', '中国象棋'],
  },
  {
    id: 'home-service',
    title: '家庭服务',
    icon: Home,
    color: 'from-teal-500/30 to-teal-500/10',
    intents: ['小雅家政', '家政服务', '家电维修', '房屋维修', '水电维修', '母婴服务', '中医足道'],
  },
  {
    id: 'mall',
    title: '智慧商城',
    icon: ShoppingBag,
    color: 'from-fuchsia-500/30 to-fuchsia-500/10',
    intents: [
      '商城',
      '数字健康机器人',
      '健康监测终端',
      '智慧生活终端',
      '健康食疗产品',
      '适老化用品',
      '日常生活用品',
      '订单页面',
    ],
  },
  {
    id: 'fallback',
    title: '异常兜底',
    icon: Headset,
    color: 'from-slate-400/30 to-slate-400/10',
    intents: ['未知指令'],
  },
]
