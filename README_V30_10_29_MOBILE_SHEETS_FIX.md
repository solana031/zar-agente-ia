# ZAR v30.10.29 — Mobile scroll/floating controls + Google Sheets edit fix

- Mobile chat is now an explicit full-height scroll surface; the last assistant message can be reached and read completely.
- ZAR home logo remains inside that scroll surface and leaves through the top when scrolling.
- Hora / Recordar / Correo are compact floating pills with no shared background bar.
- Aprendizajes activos is a smaller floating status pill.
- Google Sheets edits accept a spreadsheet URL or ID, normalize URL-encoded A1 ranges, qualify bare ranges with the first sheet tab, sanitize values, and return clearer API errors.
