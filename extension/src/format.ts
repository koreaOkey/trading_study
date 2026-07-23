export const ASSESSMENT_LABELS: Readonly<Record<string, string>> = {
  balanced: "균형",
  insufficient: "근거 부족",
  overconfirmed: "과잉 확신",
  conflicted: "상충",
}

export const HYPOTHESIS_LABELS: Readonly<Record<string, string>> = {
  golden_cross_expected: "골든크로스 예상",
  dead_cross_expected: "데드크로스 예상",
  uncertain: "방향 미확정",
  long: "롱",
  short: "숏",
  watch: "관찰",
  skip: "패스",
}

export const assessmentLabel = (assessment: string): string =>
  ASSESSMENT_LABELS[assessment] ?? assessment

export const hypothesisLabel = (hypothesis: string): string =>
  HYPOTHESIS_LABELS[hypothesis] ?? hypothesis

export const timeframeLabel = (timeframe: string): string => {
  if (/^\d+$/.test(timeframe)) {
    const minutes = Number.parseInt(timeframe, 10)
    if (minutes >= 60 && minutes % 60 === 0) {
      return `${minutes / 60}시간봉`
    }
    return `${minutes}분봉`
  }
  const upper = timeframe.toUpperCase()
  if (upper === "D" || upper === "1D") {
    return "일봉"
  }
  if (upper === "W" || upper === "1W") {
    return "주봉"
  }
  return timeframe
}

export const formatPrice = (raw: string | null): string => {
  if (raw === null) {
    return "―"
  }
  const value = Number.parseFloat(raw)
  if (Number.isNaN(value)) {
    return raw
  }
  const rounded = Math.abs(value) >= 1000 ? Math.round(value) : value
  return rounded.toLocaleString("ko-KR")
}

export const formatPercent = (raw: string | null, digits = 1): string => {
  if (raw === null) {
    return "―"
  }
  const value = Number.parseFloat(raw)
  if (Number.isNaN(value)) {
    return raw
  }
  return `${value.toFixed(digits)}%`
}

export const formatDecisionTime = (iso: string): string => {
  const match = iso.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/)
  if (match === null) {
    return iso
  }
  const [, year, month, day, hour, minute] = match
  return `${year}-${month}-${day} ${hour}:${minute}`
}
