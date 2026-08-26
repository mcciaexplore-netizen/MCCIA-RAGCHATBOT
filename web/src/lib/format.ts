const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

/** "2021-06" -> "June 2021" */
export function formatIssueMonth(issueMonth: string): string {
  const [yearStr, monthStr] = issueMonth.split("-");
  const monthIndex = Number(monthStr) - 1;
  const monthName = MONTH_NAMES[monthIndex];
  if (!monthName || !yearStr) return issueMonth;
  return `${monthName} ${yearStr}`;
}
