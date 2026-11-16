import { DayPicker } from 'react-day-picker'
import { enUS } from 'date-fns/locale'
import 'react-day-picker/style.css'

export default function Calendar(props: { selected: Date; onSelect: (date: Date) => void }) {
  return (
    <DayPicker
      mode="single"
      selected={props.selected}
      onSelect={(date) => { if (date) props.onSelect(date) }}
      defaultMonth={props.selected}
      showOutsideDays
      fixedWeeks
      weekStartsOn={1}
      locale={{
        ...enUS,
        localize: {
          ...enUS.localize,
          month: (index) => new Intl.DateTimeFormat('zh-CN', { month: 'long' }).format(new Date(2024, index)),
          day: (index) => ['日', '一', '二', '三', '四', '五', '六'][index],
        },
        options: { ...enUS.options, weekStartsOn: 1 },
      }}
      className="shadcn-calendar"
      classNames={{
        root: 'shadcn-calendar-root',
        months: 'rdp-months',
        month: 'rdp-month',
        month_caption: 'rdp-month-caption',
        caption_label: 'rdp-caption-label',
        nav: 'rdp-nav',
        button_previous: 'rdp-nav-button rdp-previous',
        button_next: 'rdp-nav-button rdp-next',
        month_grid: 'rdp-month-grid',
        weekdays: 'rdp-weekdays',
        weekday: 'rdp-weekday',
        weeks: 'rdp-weeks',
        week: 'rdp-week',
        day: 'rdp-day',
        day_button: 'rdp-day-button',
        today: 'rdp-today',
        selected: 'rdp-selected',
        outside: 'rdp-outside',
        focused: 'rdp-focused',
        disabled: 'rdp-disabled',
        hidden: 'rdp-hidden',
      }}
    />
  )
}
