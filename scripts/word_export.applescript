-- Kullanım: osascript word_export.applescript <girdi> <çıktı> <belge-adı> <pdf|docx>
-- Girdi ve çıktı, Word'ün sandbox kapsayıcısında olmalıdır (izin penceresi çıkmaması için).
on run argv
	set inPath to item 1 of argv
	set outPath to item 2 of argv
	set docName to item 3 of argv
	set outKind to item 4 of argv
	set AppleScript's text item delimiters to "."
	set baseName to text item 1 of docName
	set AppleScript's text item delimiters to "/"
	set outName to last text item of outPath
	set AppleScript's text item delimiters to ""
	set stage to "açma"
	tell application "Microsoft Word"
		set display alerts to alerts none
		try
			open (POSIX file inPath)
			set theName to missing value
			repeat 600 times
				repeat with n in {docName, baseName}
					try
						set theName to name of document (contents of n)
						exit repeat
					end try
				end repeat
				if theName is not missing value then exit repeat
				delay 0.2
			end repeat
			if theName is missing value then error "Word belgeyi açamadı"
			set stage to "kaydetme"
			if outKind is "pdf" then
				save as document theName file name outPath file format format PDF
			else
				save as document theName file name outPath file format format document
			end if
			set stage to "kapatma"
			-- "Farklı kaydet" sonrası belge adı değişebilir; iki adı da dene
			try
				close document theName saving no
			on error
				close document outName saving no
			end try
		on error errMsg
			repeat with n in {outName, docName, baseName}
				try
					close document (contents of n) saving no
				end try
			end repeat
			set display alerts to alerts all
			error stage & ": " & errMsg
		end try
		set display alerts to alerts all
	end tell
end run
