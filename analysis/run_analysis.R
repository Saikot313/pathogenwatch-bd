#!/usr/bin/env Rscript
# Base-R cross-language reproducibility script for WHO FluNet CSV.
# Usage: Rscript analysis/run_analysis.R data/raw/VIW_FNT.csv data/processed/r_analysis
args <- commandArgs(trailingOnly = TRUE)
input <- if (length(args) >= 1) args[1] else "data/raw/VIW_FNT.csv"
outdir <- if (length(args) >= 2) args[2] else "data/processed/r_analysis"
dir.create(outdir, recursive = TRUE, showWarnings = FALSE)
if (!file.exists(input)) stop("Input CSV not found: ", input)
raw <- read.csv(input, check.names = FALSE, stringsAsFactors = FALSE, na.strings = c("", "NA", "N/A"))
required <- c("COUNTRY_CODE", "ISO_YEAR", "ISO_WEEK", "ISO_WEEKSTARTDATE", "ORIGIN_SOURCE", "SPEC_PROCESSED_NB", "INF_A", "INF_B", "INF_ALL")
missing <- setdiff(required, names(raw))
if (length(missing)) stop("Missing required columns: ", paste(missing, collapse = ", "))
numcols <- intersect(c("ISO_YEAR", "ISO_WEEK", "SPEC_PROCESSED_NB", "SPEC_RECEIVED_NB", "INF_A", "INF_B", "INF_ALL", "INF_NEGATIVE"), names(raw))
for (nm in numcols) raw[[nm]] <- suppressWarnings(as.numeric(raw[[nm]]))
raw$ISO_WEEKSTARTDATE <- as.Date(raw$ISO_WEEKSTARTDATE)
raw <- raw[!duplicated(raw), , drop = FALSE]
can_recover <- is.na(raw$INF_ALL) & !is.na(raw$INF_A) & !is.na(raw$INF_B)
raw$INF_ALL_RECOVERED <- can_recover
raw$INF_ALL[can_recover] <- raw$INF_A[can_recover] + raw$INF_B[can_recover]
write.csv(data.frame(metric=c("raw_rows","exact_duplicates_removed","inf_all_recovered"), value=c(nrow(read.csv(input, check.names=FALSE)), nrow(read.csv(input, check.names=FALSE))-nrow(raw), sum(can_recover))), file.path(outdir,"r_data_quality_report.csv"), row.names=FALSE)
# Preserve source strata, then apply documented national-total preference per country-week.
key <- paste(raw$COUNTRY_CODE, raw$ISO_YEAR, raw$ISO_WEEK, sep="_")
has_nd <- tapply(raw$ORIGIN_SOURCE == "NOTDEFINED", key, function(x) any(x, na.rm=TRUE))
use <- !(raw$ORIGIN_SOURCE != "NOTDEFINED" & has_nd[key])
kept <- raw[use, , drop=FALSE]
countcols <- intersect(c("SPEC_PROCESSED_NB","SPEC_RECEIVED_NB","INF_A","INF_B","INF_ALL","INF_NEGATIVE"), names(kept))
# Collapse to one country-week after source priority. Summation is NA-preserving.
agg_key <- paste(kept$COUNTRY_CODE, kept$ISO_YEAR, kept$ISO_WEEK, sep="_")
rows <- lapply(split(seq_len(nrow(kept)), agg_key), function(ix) {
  z <- kept[ix, , drop=FALSE]
  out <- z[1, c("COUNTRY_CODE","ISO_YEAR","ISO_WEEK","ISO_WEEKSTARTDATE"), drop=FALSE]
  for (nm in countcols) out[[nm]] <- if (all(is.na(z[[nm]]))) NA_real_ else sum(z[[nm]], na.rm=TRUE)
  out
})
weekly <- do.call(rbind, rows); rownames(weekly) <- NULL
weekly$positivity <- ifelse(!is.na(weekly$SPEC_PROCESSED_NB) & weekly$SPEC_PROCESSED_NB > 0, weekly$INF_ALL / weekly$SPEC_PROCESSED_NB, NA_real_)
write.csv(weekly, file.path(outdir,"r_country_week_analysis.csv"), row.names=FALSE)
bgd <- weekly[weekly$COUNTRY_CODE == "BGD", , drop=FALSE]
bgd <- bgd[order(bgd$ISO_WEEKSTARTDATE), , drop=FALSE]
write.csv(bgd, file.path(outdir,"r_bangladesh_weekly.csv"), row.names=FALSE)
annual <- aggregate(cbind(INF_ALL, SPEC_PROCESSED_NB) ~ ISO_YEAR, data=bgd, FUN=function(x) if(all(is.na(x))) NA_real_ else sum(x,na.rm=TRUE))
annual$positivity <- ifelse(annual$SPEC_PROCESSED_NB > 0, annual$INF_ALL / annual$SPEC_PROCESSED_NB, NA_real_)
write.csv(annual, file.path(outdir,"r_bangladesh_annual.csv"), row.names=FALSE)
writeLines(c("PathogenWatch BD R analysis summary", paste("Input:", normalizePath(input)), paste("Rows after exact de-duplication:", nrow(raw)), paste("INF_ALL values recovered:", sum(can_recover)), paste("Country-week rows:", nrow(weekly)), paste("Bangladesh country-week rows:", nrow(bgd)), "Interpretation: FluNet detections reflect surveillance/testing and are not total clinical infections."), file.path(outdir,"r_analysis_summary.txt"))
cat("R analysis completed. Outputs written to:", normalizePath(outdir), "\n")
