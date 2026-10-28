param(
  [Parameter(Mandatory = $true)][string]$InputDir,
  [Parameter(Mandatory = $true)][string]$Expected,
  [Parameter(Mandatory = $true)][string]$Output
)

$ErrorActionPreference = "Stop"
$expectedObject = Get-Content -LiteralPath $Expected -Raw -Encoding UTF8 | ConvertFrom-Json
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
$results = @()

try {
  foreach ($sample in $expectedObject.samples) {
    $path = Join-Path $InputDir $sample.file
    $doc = $word.Documents.Open($path, $false, $true)
    try {
      $doc.Repaginate()
      $pages = [int]$doc.ComputeStatistics(2)
      $pageTexts = @()
      $pageShapeCounts = @()
      for ($i = 1; $i -le $pages; $i++) {
        $start = $doc.GoTo(1, 1, $i).Start
        if ($i -lt $pages) {
          $end = $doc.GoTo(1, 1, $i + 1).Start
        } else {
          $end = $doc.Content.End
        }
        $pageTexts += $doc.Range($start, $end).Text
        $pageShapeCounts += 0
      }

      $shapeInfo = @()
      for ($i = 1; $i -le $doc.InlineShapes.Count; $i++) {
        $shape = $doc.InlineShapes.Item($i)
        $page = [int]$shape.Range.Information(3)
        if ($page -ge 1 -and $page -le $pages) {
          $pageShapeCounts[$page - 1] = $pageShapeCounts[$page - 1] + 1
        }
        $shapeInfo += [pscustomobject]@{
          width = [double]$shape.Width
          height = [double]$shape.Height
          type = [int]$shape.Type
          page = $page
        }
      }

      $titlePages = @()
      foreach ($title in $sample.titles) {
        $found = -1
        for ($i = 0; $i -lt $pages; $i++) {
          if ($pageTexts[$i].Contains([string]$title)) {
            $found = $i + 1
            break
          }
        }
        $titlePages += $found
      }

      $contentText = $doc.Content.Text
      $captionPrinted = $false
      if ($null -ne $sample.caption -and ([string]$sample.caption).Length -gt 0) {
        $captionPrinted = $contentText.Contains([string]$sample.caption)
      }

      $cellSizes = @()
      $tableRows = 0
      $tableColumns = 0
      if ($doc.Tables.Count -ge 1) {
        $table = $doc.Tables.Item(1)
        $tableRows = [int]$table.Rows.Count
        $tableColumns = [int]$table.Columns.Count
        $cellSizes += [double]$table.Cell(1, 2).Range.Font.Size
        $cellSizes += [double]$table.Cell(5, 2).Range.Font.Size
        $cellSizes += [double]$table.Cell(7, 2).Range.Font.Size
      }

      $lastPageText = ""
      $lastPageShapes = 0
      $pageVisibleLengths = @()
      foreach ($text in $pageTexts) {
        $visible = ([string]$text) -replace "[\s]", ""
        $pageVisibleLengths += $visible.Length
      }
      if ($pages -ge 1) {
        $lastPageText = [string]$pageTexts[$pages - 1]
        $lastPageShapes = [int]$pageShapeCounts[$pages - 1]
      }
      $lastPageVisibleLength = 0
      if ($pageVisibleLengths.Count -ge 1) {
        $lastPageVisibleLength = [int]$pageVisibleLengths[$pages - 1]
      }

      $results += [pscustomobject]@{
        file = $sample.file
        pages = $pages
        tables = [int]$doc.Tables.Count
        table_rows = $tableRows
        table_columns = $tableColumns
        inline_shapes = [int]$doc.InlineShapes.Count
        page_width = [double]$doc.PageSetup.PageWidth
        page_height = [double]$doc.PageSetup.PageHeight
        orientation = [int]$doc.PageSetup.Orientation
        margin_top = [double]$doc.PageSetup.TopMargin
        margin_bottom = [double]$doc.PageSetup.BottomMargin
        margin_left = [double]$doc.PageSetup.LeftMargin
        margin_right = [double]$doc.PageSetup.RightMargin
        title_size = [double]$doc.Paragraphs.Item(1).Range.Font.Size
        title_bold = [int]$doc.Paragraphs.Item(1).Range.Font.Bold
        title_alignment = [int]$doc.Paragraphs.Item(1).Alignment
        cell_sizes = $cellSizes
        title_pages = $titlePages
        page_text_lengths = @($pageTexts | ForEach-Object { $_.Length })
        page_visible_lengths = $pageVisibleLengths
        page_shape_counts = $pageShapeCounts
        last_page_text_length = $lastPageText.Length
        last_page_visible_length = $lastPageVisibleLength
        last_page_shapes = $lastPageShapes
        word_version = [string]$word.Version
        word_build = [string]$word.Build
        caption_printed = $captionPrinted
        shapes = $shapeInfo
      }
    } finally {
      $doc.Close(0)
    }
  }
} finally {
  $word.Quit()
}

$results | ConvertTo-Json -Depth 10 | Out-File -LiteralPath $Output -Encoding utf8
Write-Output ("inspected " + $results.Count + " samples")
