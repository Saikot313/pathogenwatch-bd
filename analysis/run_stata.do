* PathogenWatch BD: Stata cross-language descriptive analysis
* Run from project root: do "analysis/run_stata.do"
version 16.0
clear all
set more off
local input "data/raw/VIW_FNT.csv"
cap mkdir "data/processed/stata_analysis"
import delimited using "`input'", clear varnames(1) case(preserve) stringcols(_all) bindquote(strict)
foreach v in ISO_YEAR ISO_WEEK SPEC_PROCESSED_NB SPEC_RECEIVED_NB INF_A INF_B INF_ALL INF_NEGATIVE {
    capture destring `v', replace force
}
* Remove only exact duplicate source rows.
duplicates drop
* Recover INF_ALL only when both component counts are available.
gen byte INF_ALL_RECOVERED = missing(INF_ALL) & !missing(INF_A) & !missing(INF_B)
replace INF_ALL = INF_A + INF_B if INF_ALL_RECOVERED == 1
* Keep Bangladesh for the Stata reproducibility table.
keep if COUNTRY_CODE == "BGD"
* Determine country-week keys containing NOTDEFINED; prefer those rows over other sources.
generate byte _is_nd = (ORIGIN_SOURCE == "NOTDEFINED")
bysort COUNTRY_CODE ISO_YEAR ISO_WEEK: egen byte _has_nd = max(_is_nd)
keep if _has_nd == 0 | _is_nd == 1
* The preceding keep retains only NOTDEFINED where present, otherwise all source rows.
collapse (sum) SPEC_PROCESSED_NB SPEC_RECEIVED_NB INF_A INF_B INF_ALL INF_NEGATIVE (max) INF_ALL_RECOVERED, by(COUNTRY_CODE ISO_YEAR ISO_WEEK ISO_WEEKSTARTDATE)
gen double positivity = INF_ALL / SPEC_PROCESSED_NB if SPEC_PROCESSED_NB > 0 & !missing(INF_ALL)
order COUNTRY_CODE ISO_YEAR ISO_WEEK ISO_WEEKSTARTDATE SPEC_PROCESSED_NB INF_ALL positivity
export delimited using "data/processed/stata_bangladesh_weekly.csv", replace
preserve
collapse (sum) INF_ALL SPEC_PROCESSED_NB, by(ISO_YEAR)
gen double positivity = INF_ALL / SPEC_PROCESSED_NB if SPEC_PROCESSED_NB > 0
export delimited using "data/processed/stata_bangladesh_annual.csv", replace
restore
log using "data/processed/stata_analysis.log", text replace
display "PathogenWatch BD Stata analysis completed."
count
summarize INF_ALL SPEC_PROCESSED_NB positivity
log close
