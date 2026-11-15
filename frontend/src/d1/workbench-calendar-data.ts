/**
 * Hand-maintained festival and annual PRC holiday schedules for the
 * workbench calendar.
 *
 * Festivals and annual rest/work schedules are independent: a festival name
 * never implies a day off, and a day is not marked as an official holiday
 * unless that year's schedule is present below. Only the verified 2026 and
 * 2027 notices are loaded; every other year must say the annual schedule is
 * not loaded. No teaching-calendar data is read or changed.
 *
 * Solar terms and the official lunar snapshot live in the generated
 * `workbench-calendar-solar-terms.ts` and `workbench-calendar-hko-lunar.ts`
 * files. Both derive from the HKO 1901-2100 annual tables; the lunar file also
 * records the Taipei Astronomical Museum 1900/1901 bootstrap source.
 */

export interface AnnualHolidaySchedule {
  readonly rest: readonly string[]
  readonly makeup: readonly string[]
  readonly source: string
}

export const ANNUAL_HOLIDAY_SOURCES: Readonly<Record<number, string>> = {
  2026: 'https://www.beijing.gov.cn/cs/gncs/zcwj/202603/t20260327_4568275.html',
  2027: 'https://chinajob.mohrss.gov.cn/h5/c/2026-11-09/635850.shtml',
}

export const ANNUAL_HOLIDAYS: Readonly<Record<number, AnnualHolidaySchedule>> = {
  2026: {
    rest: [
      '2026-01-01', '2026-01-02', '2026-01-03',
      '2026-02-15', '2026-02-16', '2026-02-17', '2026-02-18',
      '2026-02-19', '2026-02-20', '2026-02-21', '2026-02-22', '2026-02-23',
      '2026-04-04', '2026-04-05', '2026-04-06',
      '2026-05-01', '2026-05-02', '2026-05-03', '2026-05-04', '2026-05-05',
      '2026-06-19', '2026-06-20', '2026-06-21',
      '2026-09-25', '2026-09-26', '2026-09-27',
      '2026-10-01', '2026-10-02', '2026-10-03', '2026-10-04',
      '2026-10-05', '2026-10-06', '2026-10-07',
    ],
    makeup: [
      '2026-01-04', '2026-02-14', '2026-02-28',
      '2026-05-09', '2026-09-20', '2026-10-10',
    ],
    source: ANNUAL_HOLIDAY_SOURCES[2026],
  },
  2027: {
    rest: [
      '2027-01-01', '2027-01-02', '2027-01-03',
      '2027-02-05', '2027-02-06', '2027-02-07', '2027-02-08',
      '2027-02-09', '2027-02-10', '2027-02-11', '2027-02-12', '2027-02-13',
      '2027-04-03', '2027-04-04', '2027-04-05',
      '2027-05-01', '2027-05-02', '2027-05-03', '2027-05-04', '2027-05-05',
      '2027-06-09',
      '2027-09-15',
      '2027-10-01', '2027-10-02', '2027-10-03', '2027-10-04',
      '2027-10-05', '2027-10-06', '2027-10-07',
    ],
    makeup: [
      '2027-01-31', '2027-02-14', '2027-05-08',
      '2027-09-26', '2027-10-09',
    ],
    source: ANNUAL_HOLIDAY_SOURCES[2027],
  },
}

/** Fixed Gregorian festivals. A label does not imply an official day off. */
export const FIXED_FESTIVALS: Readonly<Record<string, string>> = {
  '01-01': '元旦',
  '03-08': '妇女节',
  '03-12': '植树节',
  '05-01': '劳动节',
  '05-04': '青年节',
  '06-01': '儿童节',
  '07-01': '建党节',
  '08-01': '建军节',
  '09-10': '教师节',
  '10-01': '国庆节',
  '11-08': '记者节',
  '12-04': '国家宪法日',
}

/**
 * Lunar festivals keyed by lunar month-day. Leap-month dates never match
 * these keys; 除夕 is computed from the actual day before lunar New Year.
 */
export const LUNAR_FESTIVALS: Readonly<Record<string, string>> = {
  '1-1': '春节',
  '1-15': '元宵节',
  '2-2': '龙抬头',
  '5-5': '端午节',
  '7-7': '七夕节',
  '7-15': '中元节',
  '8-15': '中秋节',
  '9-9': '重阳节',
  '12-8': '腊八节',
}

export const FESTIVAL_SOURCE_NOTE =
  '常见公历／农历节日名称仅作日期标识，不等同于法定放假；' +
  '实际放假与调休只使用已载入的年度通知。'

export const CALENDAR_SOURCE_NOTE =
  '农历与节气来自香港天文台 1901–2100 离线年表；' +
  '节日名称不等同法定放假；年度安排仅 2026、2027 已载入。'
