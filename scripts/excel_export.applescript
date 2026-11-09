-- Kullanım: osascript excel_export.applescript <girdi> <çıktı> <çalışma-kitabı-adı>
-- Girdi ve çıktı, Excel'in sandbox kapsayıcısında olmalıdır (izin penceresi çıkmaması için).
-- Excel önceden kapalıysa iş bitince kapatılır; açık olan Excel'e (kullanıcının belgelerine) dokunulmaz.
on run argv
	set inPath to item 1 of argv
	set outPath to item 2 of argv
	set bookName to item 3 of argv
	set stage to "açma"
	set wasRunning to application "Microsoft Excel" is running
	tell application "Microsoft Excel"
		set display alerts to false
		try
			open (POSIX file inPath)
			set wb to missing value
			repeat 600 times
				try
					set wb to workbook bookName
					exit repeat
				end try
				delay 0.2
			end repeat
			if wb is missing value then error "Excel dosyayı açamadı"
			set stage to "kaydetme"
			save workbook as wb filename outPath file format PDF file format
			set stage to "kapatma"
			close wb saving no
		on error errMsg
			try
				close workbook bookName saving no
			end try
			set display alerts to true
			if not wasRunning then quit saving no
			error stage & ": " & errMsg
		end try
		set display alerts to true
		if not wasRunning then quit saving no
	end tell
end run
