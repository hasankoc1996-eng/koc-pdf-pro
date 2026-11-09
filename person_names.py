"""KVKK karartması için ad soyad bulma (çevrimdışı, sözlükle).

Belgede büyük harfle başlayan kelime dizileri aranır. Dizi sık kullanılan bir Türkçe adla başlıyorsa
(Ayşe Demir, MEHMET ALİ YILMAZ) ya da bir ipucunun ardından geliyorsa (Davacı:, Av., Adı Soyadı:…) ad soyad
sayılır. Kurum, yer, unvan gibi kelimeler diziyi bitirir; böylece "Deniz Kuvvetleri", "Ali Bey" alınmaz.
Liste her adı bilemez: bulunanlar kullanıcıya listelenir, eksik kalanlar ek kelime olarak aranabilir."""

import re

_FOLD = str.maketrans("çğıöşüâîû", "cgiosuaiu")


def _norm(word):
    """Karşılaştırma biçimi: küçük harf, Türkçe harfler sadeleşmiş (AYŞE, Ayşe, Ayse → ayse; harfleri
    bozuk çıkan PDF'lerde de tanınsın)."""
    return word.replace("İ", "i").lower().replace("\u0307", "").translate(_FOLD)


ADLAR = frozenset(map(_norm, """
abdullah abdulkadir abdurrahman abdülhamit abdülkadir abdülkerim abdülvahap adem adil adnan ahmet akif alaattin
ali alican alp alparslan alper alpay alptekin anıl arda arif aras arslan asaf aslan ata atakan atilla ayaz aybars
ayberk aydın ayhan aykut aytaç aytekin aziz bahadır bahattin baki baran barış batu batuhan battal bayram bedir
bedirhan bedri behçet bekir berat berk berkan berkant berkay beytullah bilal bilgehan birol bora burak burhan buğra
bülent can caner celal celalettin cem cemal cemil cengiz cevat cevdet cihan cihangir coşkun cumali cüneyt çağan
çağatay çağlar çağrı çetin çınar davut deniz doğan doğukan doruk durmuş dursun ebubekir ecevit efe efkan egehan
egemen ekrem emin emir emircan emirhan emrah emre emrullah ender engin enes enis enver eray erbil ercan erdal erdem
erdinç erdoğan eren ergin ergün erhan erkam erkan erkut erol ersan ersin ersoy ertan ertuğrul esat eşref ethem
evren eymen eyüp fahri faik faruk fatih fazıl fehmi ferhat ferit fethi fevzi feyzullah fikret fırat fuat furkan
gani garip gazi gökay gökhan gökmen göktuğ göktürk görkem güngör gürkan gürsel güven habib habip hacı hafız hakan
hakkı halil halis halit haluk hamdi hami hamit hamza harun hasan hasbi haydar hayati hayri hıdır hikmet hilmi
hulki hulusi hurşit hüsamettin hüseyin hüsnü ibrahim idris ihsan ilhami ilhan ilkay ilker ilyas irfan ismail
ismet izzet kaan kadir kadri kamil kâmil kasım kayhan kazım kâzım kemal kenan kerem kubilay kudret kutay kuzey
kürşat latif levent lokman lütfi macit mahir mahmut mahsun mazlum mecit medet mehdi mehmet melih memduh mert mesut
metehan metin mevlüt mikail miraç miran mithat muammer muhammed muhammet muharrem muhittin muhsin murat musa
mustafa muzaffer mücahit mümin münir mürsel naci nadir nafi nail namık nazif nazım nebi necati necdet necip
necmettin necmi nedim nejat nevzat nihat nizamettin niyazi nuh numan nuri nurettin nurullah nusret oğuz oğuzhan
okan oktay onur orçun orhan osman ozan ömer ömür önder özcan özgür rafet ragıp rahim rahmi raif ramazan ramiz rasim
raşit rauf recai recep reha remzi resul reşat reşit rıdvan rıfat rıza rifat rüstem rüştü sabahattin sabit sabri
sadık sadullah saffet sait salih samet sami sarp savaş sebahattin sedat sefa selahattin selami selçuk selim semih
serdar serhat serkan sertaç server sezai sezer sezgin seyfettin seyfi seyit sıddık sinan sırrı soner suat
süleyman şaban şahin şakir şamil şefik şemsettin şener şenol şeref şerif şevket şevki şinasi şükrü taci tacettin
taha tahir talat talha tamer taner tanju tarık tarkan taylan tayfun tayyip tekin teoman tevfik timur toygar tolga
tufan tuğrul tuna tunç tuncay turan turgay turgut tümer uğur ulaş umur umut utku ufuk ümit ünal vahit vedat veli
volkan vural yağız yahya yakup yalçın yalın yasin yasir yavuz yaşar yekta yener yıldırım yıldıray yılmaz yiğit
yunus yusuf yücel yüksel zafer zahit zekai zeki zekeriya zeynel zihni ziya zübeyir zülfikar
ada asel asiye aslı aslıhan asuman asya ayça ayfer aygül ayla aylin aynur aysel aysu aysun ayşe ayşegül ayten azra
bahar banu başak belgin belma bengisu bengü beren berna berra berrin betül beyza bihter bilge birgül birsen buket
burcu burçin büşra canan cansu cemile cennet ceren ceylan çağla çiğdem damla defne demet derin derya dicle didem
dila dilan dilara dilber dilek doğa dudu duru duygu ebru ecem ece ecrin eda ela elçin elif elvan emel emine esengül
esin esila esma esmeray esra eylül ezgi fadime fatma fatoş feride ferda feyza feyzanur fidan figen filiz funda
gamze gizem gonca gökçe gözde gül gülay gülben gülcan gülden gülizar gülnur gülsen gülsüm gülşah gülşen gülten
gülümser günay güner güler hacer hale halime hamiyet handan hande hanife hatice havva hayriye hazal helin hicran
hilal hiranur hülya hümeyra ılgın ırmak ışıl iclal ilayda ilke ilknur inci ipek irem jale kader kadriye kamile
kardelen kevser kezban kıymet kumsal kübra lale lara latife leyla lütfiye makbule masal medine mehtap melahat melda
melek melike melis melisa meltem meral merve meryem mihriban mine miray müberra müge mükerrem münevver müzeyyen
naciye nagehan naime nalan naz nazan nazife nazlı nazmiye nebahat necla nedime nefise nehir nergis neriman nesibe
nesli neslihan nesrin nevin nezahat nida nihal nilay nilgün nilüfer nimet nisa nisanur nur nuran nuray nurcan
nurgül nurhan nursel nursen nurşen nurten oya öykü özden özge özgül özlem pakize pelin pembe perihan pervin pınar
rabia rahime rana raziye remziye reyhan rezzan rukiye rumeysa rüveyda saadet sabahat sabiha sabriye sacide safiye
sakine saliha sare seda sedanur sedef seher selda selen selin selma sema semahat semanur semiha semra sena serap
serenay serpil serra sevda sevgi sevgül sevil sevim sevinç sevtap sıdıka sıla sibel simge sinem songül su sude
sudenaz suna süheyla sultan sümeyye şahika şaziye şenay şengül şerife şeyma şevval şule şükran tijen tuana tuba
tuğba tuğçe tülay tülin türkan ülkü ümmügülsüm ümmühan ümmü ümran vildan yağmur yaprak yaren yasemin yeliz yeşim
yıldız yurdagül zahide zarife zehra zekiye zeliha zerrin zeynep zişan zuhal zübeyde zühal zühre zümra
""".split()))

# Ad soyad dizisini bitiren (ya da başlatamayan) kelimeler: unvan, akrabalık, rol, kurum, yer, adres, ay/gün…
DURAK = frozenset(map(_norm, """
bey beyefendi hanım hanımefendi efendi paşa ağa hoca hocası usta abla abi ağabey amca dayı teyze hala dede nine
eşi oğlu kızı annesi babası mirasçı mirasçısı mirasçıları varis varisi muris
davacı davacılar davalı davalılar vekil vekili vekilleri avukat av sanık sanıklar şüpheli müşteki mağdur katılan
tanık tanıklar bilirkişi hakim hâkim hakimi hâkimi katip kâtip katibi kâtibi zabıt başkan başkanı üye üyesi savcı
savcısı cumhuriyet başsavcılığı mahkeme mahkemesi mahkemesine icra iflas dairesi daire esas karar dosya dosyası
sayılı tarihli tarih konu ilgi ek dilekçe dilekçesi talep sonuç hüküm gerekçe gerekçeli tutanak tutanağı imza
müdürlüğü müdür müdürü başkanlığı bakanlığı bakanlık valiliği kaymakamlığı belediyesi belediye üniversitesi
fakültesi hastanesi bankası banka şubesi şube sigorta sigortası holding şirketi şirket ticaret sanayi limited
anonim ltd şti aş inşaat turizm gıda otomotiv tekstil elektronik yazılım teknoloji pazarlama lojistik enerji grup
vakfı vakıf derneği dernek odası birliği kurumu kurulu heyeti komisyonu komutanlığı kuvvetleri merkezi merkez
enstitüsü okulu lisesi baro barosu noter noterliği tüketici hakem
mahallesi mahalle mah caddesi cadde cad sokak sokağı sok bulvarı bulvar apartmanı apt sitesi site blok kat no
numara numarası köyü köy ilçesi ilçe ili il meydanı parkı yolu plaza
adres adresi tel telefon faks gsm eposta mail tc kimlik vergi iban hesap
ad adı soyad soyadı isim ismi soyisim soyismi unvan unvanı ünvan ünvanı
türkiye türk devlet genel bölge memur memuru personel uzman doktor dr prof doç öğr gör mühendis öğretmen sayın sn
tarafından adına hakkında aleyhine ile ve veya ya da de için olarak
ocak şubat mart mayıs haziran temmuz ağustos ekim aralık pazartesi salı çarşamba perşembe cumartesi pazar
adana adıyaman afyonkarahisar afyon ağrı aksaray amasya ankara antalya ardahan artvin aydın balıkesir bartın
batman bayburt bilecik bingöl bitlis bolu burdur bursa çanakkale çankırı çorum denizli diyarbakır düzce edirne
elazığ erzincan erzurum eskişehir gaziantep giresun gümüşhane hakkari hatay ığdır isparta istanbul izmir
kahramanmaraş karabük karaman kars kastamonu kayseri kilis kırıkkale kırklareli kırşehir kocaeli konya kütahya
malatya manisa mardin mersin muğla muş nevşehir niğde ordu osmaniye rize sakarya samsun siirt sinop sivas
şanlıurfa şırnak tekirdağ tokat trabzon tunceli uşak van yalova yozgat zonguldak anadolu
""".split()))

_UP, _LOW = "A-ZÇĞİÖŞÜÂÎÛ", "a-zçğıöşüâîû"
_WORD = re.compile(rf"(?<![\w'’])[{_UP}](?:[{_LOW}]+|[{_UP}]+)(?!\w)")   # Ayşe ya da AYŞE
_CUE = re.compile(r"(?<!\w)(?:ad[ıi]?\s*(?:ve\s+)?-?\s*soyad[ıi]?|isim\s*-?\s*soyisim|davac[ıi](?:lar)?|daval[ıi](?:lar)?"
                  r"|san[ıi]k|şüpheli|müşteki|mağdur|kat[ıi]lan|tan[ıi]k|bilirkişi|başvuran|başvuru\s+sahibi|alacakl[ıi]"
                  r"|borçlu|müvekkil|vekili?|avukat|av\.|say[ıi]n|sn\.|h[aâ]kim|k[aâ]tip|k[aâ]tibi|üye|başkan|dr\.)"
                  r"\s*[:–-]?\s*(?:(?:av|dr|prof|doç|uzm|sn)\.\s*)*", re.I)
_POSSESSIVE = ("si", "su", "gi", "gu")   # Caddesi, Bankası, Sokağı (sadeleşmiş yazım): soyad olmaz
# Bunlardan biri izlerse dizinin son kelimesi yer ya da şirket adının parçasıdır (Mustafa Kemal Bulvarı, Ahmet Yılmaz İnşaat)
_PLACE = frozenset(map(_norm, """sokak sok cadde cad bulvar bulvarı mahalle mah apt apartmanı plaza köy köyü site blok camii parkı
meydanı yolu pasajı hanı ticaret sanayi inşaat turizm gıda
otomotiv tekstil elektronik yazılım teknoloji pazarlama lojistik enerji grup holding limited anonim ltd şti aş sigorta
vakıf dernek""".split()))
_COMPANY = re.compile(r"\s*(?:A\.\s?Ş\.|LTD|Ltd|ŞTİ|Şti)")


def _place(word):
    return word in _PLACE or (len(word) >= 5 and word.endswith(_POSSESSIVE))


def _surname_ok(word):
    return word not in DURAK and not _place(word)


def _line_break_ends(text, start, nxt):
    """Satırında tek başına duran ad (imza, tablo hücresi) alttaki satıra taşmaz: "Ayşe Yılmaz / Veri sorumlusu".
    Alt satırda yalnızca o kelime varsa (dar hücrede kayan soyad) ya da ad satır ortasında başladıysa taşabilir."""
    own_line = not text[text.rfind("\n", 0, start) + 1:start].strip()
    end = text.find("\n", nxt[1])
    return own_line and bool(text[nxt[1]:end if end >= 0 else len(text)].strip())


def find_names(text):
    """Metindeki ad soyadlar: [(başlangıç, bitiş), …]."""
    toks = [(m.start(), m.end(), _norm(m.group())) for m in _WORD.finditer(text)]
    cued = {m.end() for m in _CUE.finditer(text)}
    spans, i = [], 0
    while i < len(toks):
        s, e, w = toks[i]
        listed = w in ADLAR and w not in DURAK
        if not (listed or (s in cued and _surname_ok(w))):
            i += 1
            continue
        run, given = [toks[i]], 1 if listed else 0
        j = i + 1
        while j < len(toks) and len(run) < given + 2 and len(run) < 4:
            gap = text[run[-1][1]:toks[j][0]]
            if not gap.isspace() or len(gap) > 3 or ("\n" in gap and given < len(run)):   # soyaddan sonra satır atlanmaz
                break
            if "\n" in gap and len(run) >= 2 and _line_break_ends(text, run[0][0], toks[j]):
                break
            if not _surname_ok(toks[j][2]):
                break
            if given == len(run) and toks[j][2] in ADLAR:   # ikinci ad: Mehmet Ali
                given += 1
            run.append(toks[j])
            j += 1
        if j < len(toks) and _place(toks[j][2]) and text[run[-1][1]:toks[j][0]] in (" ", "  "):
            run.pop()
        if run and _COMPANY.match(text, run[-1][1]):
            run = []
        if len(run) >= 2:
            spans.append((run[0][0], run[-1][1]))
            i = j
        else:
            i += 1
    return spans


def surnames(name):
    """Bir ad soyadın soyadları (karşılaştırma biçiminde): Ayşe Demir Kaya → {demir, kaya}, MEHMET ALİ YILMAZ → {yilmaz}."""
    toks = [_norm(t) for t in _WORD.findall(name)]
    given = 0
    while given < len(toks) and toks[given] in ADLAR:
        given += 1
    return {t for t in (toks[given:] if 0 < given < len(toks) else toks[-1:]) if len(t) >= 3}


def _in_phrase(text, m, n):
    """m kelimesi, yanındaki n kelimesiyle başka bir özel adın parçası mı? (Yıldız Teknik, Kaya Sokak, Demir Çelik)
    Tümü büyük harfli yazıda yalnızca yer/şirket kelimesine bakılır: orada her kelime büyük harflidir."""
    if n is None or text[min(m.end(), n.end()):max(m.start(), n.start())] != " ":
        return False
    word = _norm(n.group())
    return _place(word) or (not m.group().isupper() and not n.group().isupper() and word not in DURAK)


def find_words(text, wanted, skip=()):
    """`wanted` kümesindeki kelimelerin büyük harfle yazıldığı yerler (Şahin, ŞAHİN, Şahin'in, Sayın Şahin;
    "demir kapı", "Yıldız Teknik Üniversitesi" değil). `skip` aralıklarındakiler (bulunmuş ad soyadların içi) alınmaz."""
    toks = list(_WORD.finditer(text))
    out = []
    for k, m in enumerate(toks):
        if _norm(m.group()) not in wanted or any(a <= m.start() < b for a, b in skip):
            continue
        if _in_phrase(text, m, toks[k - 1] if k else None) or _in_phrase(text, m, toks[k + 1] if k + 1 < len(toks) else None):
            continue
        out.append((m.start(), m.end()))
    return out
