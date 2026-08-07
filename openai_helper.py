import os
import json
import re
import base64
from google import genai
from google.genai import types
from openai import OpenAI

gemini_api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("AI_INTEGRATIONS_GEMINI_API_KEY")
gemini_base_url = os.environ.get("AI_INTEGRATIONS_GEMINI_BASE_URL")

if gemini_base_url:
    client = genai.Client(
        api_key=gemini_api_key,
        http_options={
            'api_version': '',
            'base_url': gemini_base_url
        }
    )
else:
    client = genai.Client(api_key=gemini_api_key) if gemini_api_key else None

openai_api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("AI_INTEGRATIONS_OPENAI_API_KEY")
openai_base_url = os.environ.get("AI_INTEGRATIONS_OPENAI_BASE_URL")

if openai_base_url:
    openai_client = OpenAI(
        api_key=openai_api_key,
        base_url=openai_base_url
    )
else:
    openai_client = OpenAI(api_key=openai_api_key) if openai_api_key else None



def _extract_json(text):
    if not text:
        return None
    text = text.strip()
    while text.startswith("```json") or text.startswith("```"):
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        text = text.strip()
    while text.endswith("```"):
        text = text[:-3].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r'[\[\{]', text)
    if match:
        start = match.start()
        stack = []
        in_string = False
        escape = False
        openers = {'{', '['}
        closers = {'}': '{', ']': '['}
        for i in range(start, len(text)):
            c = text[i]
            if escape:
                escape = False
                continue
            if c == '\\' and in_string:
                escape = True
                continue
            if c == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if c in openers:
                stack.append(c)
            elif c in closers:
                if stack and stack[-1] == closers[c]:
                    stack.pop()
                if not stack:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
    return None


def _extract_list(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in data:
            if isinstance(data[key], list):
                return data[key]
    return []


def discover_case_ideas(category="all", lang="tr"):
    categories_map = {
        "all": "çözülmemiş cinayetler, hırsızlık/soygun vakaları, dolandırıcılık, kayıp kişi, tuhaf olaylar, tarihsel gizemler",
        "unsolved": "çözülmemiş cinayet, kayıp kişi ve gizemli kayboluş vakaları",
        "true_crime": "gerçek suç vakaları - cinayet, soygun, dolandırıcılık, kaçakçılık",
        "weird": "tuhaf ve açıklanamayan olaylar, gizemli kayboluşlar",
        "science": "bilim gizemleri, laboratuvar kazaları ve açıklanamayan fenomenler",
        "historical": "tarihsel gizemler, çözülmemiş tarih vakaları ve tarihi suçlar"
    }
    cat_desc = categories_map.get(category, categories_map["all"])

    prompt = f"""Sen dünya çapında ünlü bir dedektiflik gizemi oyunu tasarımcısısın. Gerçek dünyadan ilham alan ama tamamen kurgusal Türkiye'ye uyarlanabilecek {cat_desc} kategorisinde 9 adet vaka fikri öner.

ÖNEMLİ: Vakalar SADECE cinayet olmak zorunda değil! Farklı suç türleri de olabilir:
- Cinayet / Şüpheli ölüm
- Hırsızlık / Soygun (müze soygunu, kasa hırsızlığı, mücevher çalınması vb.)
- Dolandırıcılık / Sahtecilik (sigorta dolandırıcılığı, sahte sanat eseri vb.)
- Kayıp kişi / Gizemli kayboluş
- Kaçakçılık / Organize suç
- Sabotaj / Kurumsal casusluk
- Kundaklama / Siber suç
Karışık suç türlerinde vakalar öner, hepsi cinayet olmasın!

Her vaka için şu bilgileri JSON formatında ver:
- title: Vakanın başlığı (Türkçe, çarpıcı ve gizemli bir isim)
- description: 4-5 cümlelik detaylı açıklama (Türkçe). Mağdurun kim olduğu, ne olduğu, nerede gerçekleştiği, kaç şüpheli olduğu ve vakanın neden ilginç olduğunu açıkla.
- category: Kategori (unsolved/true_crime/weird/science/historical)
- tags: Etiketler listesi (3-4 adet, Türkçe)
- source_type: İlham kaynağı türü (gerçek_olay/tarihi/bilimsel/kurgusal)
- difficulty: Zorluk (Kolay/Orta/Zor)
- setting: Detaylı mekan/ortam açıklaması (Türkçe, şehir ve mekan belirt)
- era: Dönem (modern/tarihi/antik)
- crime_type: Suç türü (cinayet/hirsizlik/dolandiricilik/kayip_kisi/kacakcilik/sabotaj/kundaklama/siber_suc/diger)
- victim_brief: Mağdurun kısa tanıtımı (isim, yaş, meslek) - cinayet ise "maktul", değilse "mağdur" olarak belirt
- suspect_count: Kaç şüpheli olacağı (4-6 arası)
- key_evidence: Ana kanıt türleri listesi (3-4 adet, suç türüne uygun kanıtlar)

SADECE bir JSON array döndür, başka açıklama veya metin yazma."""

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=8192,
                thinking_config=types.ThinkingConfig(thinking_budget=0)
            )
        )
        content = response.text or ""
        data = _extract_json(content)
        return _extract_list(data)
    except Exception as e:
        print(f"Gemini error: {e}")
        return []


def search_case_ideas(query):
    prompt = f"""Sen dünya çapında ünlü bir dedektiflik gizemi oyunu tasarımcısısın. Kullanıcı "{query}" araması yaptı.

Bu aramayla ilgili gerçek dünyadan ilham alan ama tamamen kurgusal Türkiye'ye uyarlanabilecek 9 adet vaka fikri öner.

ÖNEMLİ: Vakalar SADECE cinayet olmak zorunda değil! Arama terimine uygun farklı suç türleri de olabilir:
- Cinayet / Şüpheli ölüm
- Hırsızlık / Soygun
- Dolandırıcılık / Sahtecilik
- Kayıp kişi / Gizemli kayboluş
- Kaçakçılık / Organize suç
- Sabotaj / Kurumsal casusluk
- Kundaklama / Siber suç

Her vaka için şu bilgileri JSON formatında ver:
- title: Vakanın başlığı (Türkçe, çarpıcı ve gizemli bir isim)
- description: 4-5 cümlelik detaylı açıklama (Türkçe). Mağdurun kim olduğu, ne olduğu, nerede gerçekleştiği, kaç şüpheli olduğu ve vakanın neden ilginç olduğunu açıkla.
- category: Kategori (unsolved/true_crime/weird/science/historical)
- tags: Etiketler listesi (3-4 adet, Türkçe)
- source_type: İlham kaynağı türü (gerçek_olay/tarihi/bilimsel/kurgusal)
- difficulty: Zorluk (Kolay/Orta/Zor)
- setting: Detaylı mekan/ortam açıklaması (Türkçe, şehir ve mekan belirt)
- era: Dönem (modern/tarihi/antik)
- crime_type: Suç türü (cinayet/hirsizlik/dolandiricilik/kayip_kisi/kacakcilik/sabotaj/kundaklama/siber_suc/diger)
- victim_brief: Mağdurun kısa tanıtımı (isim, yaş, meslek) - cinayet ise "maktul", değilse "mağdur" olarak belirt
- suspect_count: Kaç şüpheli olacağı (4-6 arası)
- key_evidence: Ana kanıt türleri listesi (3-4 adet, suç türüne uygun kanıtlar)

SADECE bir JSON array döndür, başka açıklama veya metin yazma."""

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=8192,
                thinking_config=types.ThinkingConfig(thinking_budget=0)
            )
        )
        content = response.text or ""
        data = _extract_json(content)
        return _extract_list(data)
    except Exception as e:
        print(f"Gemini search error: {e}")
        return []


def _generate_case_structure(title, description, setting, difficulty):
    prompt = f"""Sen dedektiflik gizemi senaryocususun. Vaka fikrini senaryoya dönüştür. SADECE JSON döndür.

Başlık: {title} | Açıklama: {description} | Mekan: {setting} | Zorluk: {difficulty}

Kurallar: Türkçe yaz, Türk isimleri, Türkiye mekanı, tutarlı senaryo, cinayet olmak zorunda değil.

JSON:
{{
  "case_id": "Slug-Format",
  "title": "{title}",
  "crime_type": "cinayet/hirsizlik/dolandiricilik/kayip_kisi/kacakcilik/sabotaj/kundaklama/siber_suc/diger",
  "description": "4-5 paragraf detaylı açıklama",
  "victim": {{
    "name": "Ad Soyad", "age": 45, "occupation": "Meslek",
    "victim_type": "maktul/magdur", "incident_description": "Detaylı olay",
    "incident_date": "GG.AA.YYYY", "incident_time": "HH:MM",
    "incident_location": "Adres", "background": "3-4 cümle geçmiş"
  }},
  "suspects": [
    {{"name": "Ad Soyad", "age": 40, "occupation": "Meslek", "relation": "İlişki",
      "motive": "2-3 cümle motivasyon", "alibi": "Alibi detayı",
      "personality": "Kişilik", "suspicious_behavior": "Şüpheli davranış", "is_culprit": false}}
  ],
  "witnesses": [
    {{"name": "Ad Soyad", "occupation": "Meslek", "testimony_summary": "3-4 cümle ifade", "reliability": "Güvenilirlik"}}
  ],
  "timeline": [
    {{"time": "HH:MM", "date": "GG.AA.YYYY", "event": "Olay açıklaması", "source": "CCTV/tanık/telefon"}}
  ],
  "solution": {{
    "culprit_names": ["Suçlu adı"], "method": "3-4 cümle yöntem",
    "motive": "2-3 cümle motivasyon", "explanation": "4-5 paragraf çözüm",
    "key_clues": ["İpucu 1", "İpucu 2"]
  }},
  "culprit_keywords": "küçük harf isimler",
  "explanation_keywords": "küçük harf anahtar kelimeler",
  "investigating_unit": "Birim adı",
  "police_department": "Emniyet Müdürlüğü",
  "commissioner_name": "Başkomiser adı",
  "case_number": "2026/XXX",
  "report_letter": "<p><strong>Dedektif,</strong></p><p>Vakaya özel 3-4 paragraf HTML mektup. Vakanın konusuna, mekanına ve aciliyetine göre yazılmış resmi soruşturma mektubu. Şüpheli sayısını, kanıt türlerini, son gelişmeleri anlat. Dedektife görevini hatırlat. HTML formatında <p> etiketleri kullan.</p>",
  "report_greeting": "Şef/Komiserim/Başkomiserim (vakaya uygun hitap)",
  "report_intro_text": "Rapor giriş metni - dedektifin üstüne rapor sunarken kullanacağı 1-2 cümle (vakaya özel)",
  "report_suspect_question": "Şüpheli sorusu - oyuncuya suçlunun kim olduğunu soran vakaya özel soru (1 cümle)",
  "report_confirmation_text": "Rapor onay metni - raporun gönderilmeden önceki son uyarı metni (1-2 cümle)",
  "warning_text": "Uyarı metni - oyuncuya vakaya özel bir uyarı (1 cümle, spoiler verme gibi)",
  "instructions_text": "Talimat metni - oyuncuya vakaya özel soruşturma talimatları (2-3 cümle)"
}}

En az 5 şüpheli, 4 tanık, 15 timeline olayı oluştur.
report_letter HTML formatında olmalı (<p> etiketleri ile). Mektup vakaya özel, atmosferik ve çekici olsun."""

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=16384,
                thinking_config=types.ThinkingConfig(thinking_budget=0)
            )
        )
        return _extract_json(response.text or "")
    except Exception as e:
        print(f"Gemini case structure error: {e}")
        return None


def _generate_evidence_files(case_data):
    import json
    crime = case_data.get('crime_type', 'cinayet')
    victim = case_data.get('victim', {})
    solution = case_data.get('solution', {})
    timeline = case_data.get('timeline', [])

    suspects_detail = []
    for s in case_data.get('suspects', []):
        if isinstance(s, dict):
            suspects_detail.append(f"- {s.get('name','')} ({s.get('age','')}, {s.get('occupation','')}): {s.get('relation','')}. Motiv: {s.get('motive','')}")

    witnesses_detail = []
    for w in case_data.get('witnesses', []):
        if isinstance(w, dict):
            witnesses_detail.append(f"- {w.get('name','')} ({w.get('occupation','')}): {w.get('testimony_summary','')}")

    timeline_text = []
    for t in timeline[:10]:
        if isinstance(t, dict):
            timeline_text.append(f"- {t.get('date','')} {t.get('time','')}: {t.get('event','')}")

    victim_name = victim.get('name', '') if isinstance(victim, dict) else ''
    victim_age = victim.get('age', '') if isinstance(victim, dict) else ''
    victim_occ = victim.get('occupation', '') if isinstance(victim, dict) else ''
    victim_type = victim.get('victim_type', 'magdur') if isinstance(victim, dict) else 'magdur'
    incident_desc = victim.get('incident_description', '') if isinstance(victim, dict) else ''
    incident_date = victim.get('incident_date', '') if isinstance(victim, dict) else ''
    incident_time = victim.get('incident_time', '') if isinstance(victim, dict) else ''
    incident_loc = victim.get('incident_location', '') if isinstance(victim, dict) else ''

    crime_category_templates = {
        # CİNAYET: Türk Adli Tıp Kurumu ve Emniyet Müdürlüğü standartlarına uygun belgeler
        "cinayet": f"""1. "Olay Yeri Tutanakları": Olay_Yeri_Tespit_Tutanagi (html), Olum_Tutanagi (html), Olay_Yeri_Fotografi (image)
2. "Maktul Dosyası": Maktul_Kimlik_ve_Profil (html), Otopsi_Raporu (html), Adli_Tip_Kurumu_Raporu (html), Toksikoloji_Analizi (html)
3. "Kriminalistik Raporlar": Parmak_Izi_ve_Kriminal_Inceleme (html), Balistik_ve_Silah_Inceleme_Raporu (html), DNA_ve_Seroloji_Analiz_Raporu (html), Kriminal_Delil_Fotograflari (image)
4. "Şüpheli Profilleri": Her şüpheli için Supheli_[İsim]_Profili (html) — yaş, meslek, sabıka, motiv AYNEN olsun
5. "İfade Tutanakları": Her şüpheli için Ifade_Tutanagi_[İsim] (audio — resmi komiser sorgusu, cinayet detaylarıyla)
6. "Tanık Beyanları": Her tanık için Tanik_Ifadesi_[İsim] (audio — gözlem ve ifade, tutarlı)
7. "Gözetleme ve Teknik Delil": MOBESE_ve_CCTV_Kayitlari (image), Telefon_HTS_Kayitlari (html), Konum_ve_Baz_Istasyonu_Raporu (html)
8. "Diğer Belgeler": Sorusturma_Ozet_Raporu (html), Gazete_Haberi (html)""",

        # HIRSIZLIK: Türk Emniyet'te "Hırsızlık Büro Amirliği" standart belgeler
        "hirsizlik": f"""1. "Olay Yeri Tutanakları": Hirsizlik_Olayı_Tespit_Tutanagi (html), Olay_Yeri_Inceleme_Fotograflari (image)
2. "Mağdur Dosyası": Magdur_Kimlik_ve_Profil (html), Calinani_Mal_Tespit_Tutanagi (html), Hasar_Tespit_Raporu (html), Zarar_Gorulen_Yer_Degerlendirmesi (html)
3. "Kriminalistik Raporlar": Zorla_Giris_ve_Kirik_Iz_Inceleme_Raporu (html), Parmak_Izi_ve_Biyometrik_Raporu (html), Guvenlik_Sistemi_Analizi (html), Degerli_Esya_Tespit_Fotograflari (image)
4. "Şüpheli Profilleri": Her şüpheli için Supheli_[İsim]_Profili (html) — sabıka kaydı, yaş, meslek AYNEN olsun
5. "İfade Tutanakları": Her şüpheli için Ifade_Tutanagi_[İsim] (audio — soygun/hırsızlık detaylarıyla)
6. "Tanık Beyanları": Her tanık için Tanik_Ifadesi_[İsim] (audio)
7. "Gözetleme ve Teknik Delil": MOBESE_CCTV_Kayitlari (image), Telefon_HTS_Analizi (html), Rehin_veya_Satilan_Mal_Takibi (html)
8. "Diğer Belgeler": Sorusturma_Ozet_Raporu (html), Gazete_Haberi (html)""",

        # DOLANDIRICILIK: Mali Suçları Araştırma Kurulu (MASAK) ve Emniyet standartları
        "dolandiricilik": f"""1. "Olay Raporları": Dolandiricilik_Suç_Duyurusu_ve_Tespit (html), Kriminalistik_Belge_Inceleme_Raporu (html)
2. "Mağdur Dosyası": Magdur_Kimlik_ve_Profil (html), Mali_Inceleme_Bilirkisi_Raporu (html), Banka_Hesap_Dokumu_ve_EFT_Kayitlari (html), Sahte_Belge_Gorseli (image)
3. "MASAK/Mali Analiz": Para_Akisi_ve_Sermaye_Hareketi_Analizi (html), Sahte_Sozlesme_ve_Evrak_Incelemesi (html), Kriminalistik_Imza_ve_Muhur_Karsilastirmasi (html)
4. "Şüpheli Profilleri": Her şüpheli için Supheli_[İsim]_Profili (html) — mali geçmiş, meslek, bağlantılar AYNEN olsun
5. "İfade Tutanakları": Her şüpheli için Ifade_Tutanagi_[İsim] (audio — dolandırıcılık şeması detaylarıyla)
6. "Tanık Beyanları": Her tanık için Tanik_Ifadesi_[İsim] (audio)
7. "Dijital ve Elektronik Delil": Dijital_Yazisma_ve_E_Posta_Kayitlari (html), Arama_ve_Mesaj_Detay_Raporu (html), Ekran_Goruntuleri_ve_Dijital_Iz (image)
8. "Diğer Belgeler": Sorusturma_Ozet_Raporu (html), Gazete_Haberi (html)""",

        # KAYIP KİŞİ: Türk Emniyet "Kayıp Kişiler Bürosu" standart prosedürü
        "kayip_kisi": f"""1. "Kayıp Bildirimleri": Kayip_Kisi_Muracaat_Formu (html), Son_Gorulen_Yer_Tespit_Tutanagi (html), Arama_Kurtarma_Operasyon_Tutanagi (html)
2. "Kayıp Kişi Dosyası": Kimlik_ve_Fiziksel_Tanimlama_Formu (html), Kisisel_Esya_ve_Ozel_Isaret_Listesi (html), Saglik_Bilgileri_ve_Ozel_Notlar (html), Son_Bilinen_Aktivite_Kayitlari (html)
3. "Teknik Takip": MOBESE_Son_Gorulen_An_Kaydi (image), Telefon_HTS_ve_Konum_Analizi (html), Banka_Son_Islem_Kayitlari (html), Arama_Yapilan_Bolge_Fotograflari (image)
4. "Şüpheli Profilleri": Her şüpheli için Supheli_[İsim]_Profili (html) — kayıp kişiyle ilişki AYNEN olsun
5. "İfade Tutanakları": Her şüpheli için Ifade_Tutanagi_[İsim] (audio — kayıpla son temas ve ilişki detaylarıyla)
6. "Tanık Beyanları": Her tanık için Tanik_Ifadesi_[İsim] (audio)
7. "Basın ve Kamuoyu": Basin_Aciklamasi_ve_Kayip_Ilani (html), Ihbar_Hatti_Tutanagi (html)
8. "Diğer Belgeler": Sorusturma_Ozet_Raporu (html), Arama_Kurtarma_Koordinasyon_Belgesi (html)""",

        # KAÇAKÇILIK: Türk CMK 135 kapsamında teknik takip, gümrük ve KOM daire standartları
        "kacakcilik": f"""1. "Operasyon Tutanakları": Kacakcilik_Operasyon_Raporu (html), Musadere_Tutanagi (html), Tasit_ve_Konteyner_Arama_Tutanagi (html)
2. "El Konulan Deliller": Musadere_Edilen_Esya_Listesi (html), Kacak_Mal_Kimlik_ve_Degerleme_Raporu (html), Mali_Akis_ve_Organize_Suc_Analizi (html), Musadere_Fotografi (image)
3. "Teknik Takip (CMK 135)": Telekomunikasyon_Tespit_Tutanagi (html), Fiziki_Takip_ve_Gozlem_Tutanagi (html), Guzergah_ve_Hareket_Analizi (html), Gizli_Gozetleme_Fotograflari (image)
4. "Şüpheli Profilleri": Her şüpheli için Supheli_[İsim]_Profili (html) — örgüt içi rol, sabıka AYNEN olsun
5. "İfade Tutanakları": Her şüpheli için Ifade_Tutanagi_[İsim] (audio — kaçakçılık ağı detaylarıyla)
6. "Tanık Beyanları": Her tanık için Tanik_Ifadesi_[İsim] (audio)
7. "Gümrük ve Resmi Yazışmalar": Gumruk_İdari_Islem_Tutanagi (html), MOBESE_Gumruk_Kapisi_Kaydi (image)
8. "Diğer Belgeler": Sorusturma_Ozet_Raporu (html), Organize_Suc_Agı_Analizi (html)""",

        # SABOTAJ: Türk Jandarma İstihbarat ve KOM standartları, uluslararası sabotaj soruşturması
        "sabotaj": f"""1. "Olay Yeri Tutanakları": Sabotaj_Tespit_ve_Olay_Raporu (html), Teknik_Hasar_Tespit_Raporu (html), Olay_Yeri_Fotograflari (image)
2. "Kurum/Mağdur Dosyası": Magdur_Kurum_Profili_ve_Faaliyet_Belgesi (html), Mali_Zarar_Tespiti_Raporu (html), Guvenlik_Acigi_Degerlendirme_Raporu (html), Hasar_Fotograflari (image)
3. "Kriminalistik ve Teknik Analiz": Teknik_Uzman_Bilirkisi_Raporu (html), Sistem_Erisim_Loglari_ve_Yetkisiz_Giris (html), Fiziki_Iz_ve_Delil_Incelemesi (html)
4. "Şüpheli Profilleri": Her şüpheli için Supheli_[İsim]_Profili (html) — kuruma erişim yetkisi, motiv AYNEN olsun
5. "İfade Tutanakları": Her şüpheli için Ifade_Tutanagi_[İsim] (audio — sabotaj/casusluk bağlantısıyla)
6. "Tanık Beyanları": Her tanık için Tanik_Ifadesi_[İsim] (audio)
7. "Gözetleme ve Elektronik Delil": Guvenlik_Kamerasi_Kaydi (image), Erisim_Karti_ve_Personel_Giris_Cikis_Kayitlari (html), Ic_Yazisma_ve_E_Posta_Tespiti (html)
8. "Diğer Belgeler": Sorusturma_Ozet_Raporu (html), Kurumsal_Ic_Sorusturma_Belgesi (html)""",

        # KUNDAKLAMA: NFPA 921 standardı + Türk İtfaiye ve Adli Tıp uygulamaları
        "kundaklama": f"""1. "Olay Yeri Tutanakları": Yangin_Olay_Yeri_Tespit_Tutanagi (html), İtfaiye_Mudahale_ve_Sonuc_Tutanagi (html), Yangin_Yeri_Fotograflari (image)
2. "Yangın Orijin ve Neden Analizi (NFPA 921)": Yangin_Orijin_ve_Neden_Analizi (html), Yanik_Iz_ve_Yanma_Modeli_Raporu (html), Kimyasal_Hizlandirici_Tespit_Analizi (html), Yangin_Sonrasi_Iz_Fotograflari (image)
3. "Mağdur/Hasar Dosyası": Magdur_Profil (html), Hasar_Tespit_ve_Degerleme_Raporu (html), Sigortaci_Hasar_Tespit_Belgesi (html)
4. "Kriminalistik": Parmak_Izi_ve_DNA_Analizi (html), Yakici_Madde_Kimlik_Raporu (html)
5. "Şüpheli Profilleri": Her şüpheli için Supheli_[İsim]_Profili (html) — yangın bölgesiyle bağlantı, motiv AYNEN olsun
6. "İfade Tutanakları": Her şüpheli için Ifade_Tutanagi_[İsim] (audio — yangın gecesi hareketleriyle)
7. "Tanık Beyanları": Her tanık için Tanik_Ifadesi_[İsim] (audio)
8. "Gözetleme": Cevredeki_MOBESE_CCTV_Kaydi (image), Telefon_HTS_Yangın_Gunu (html)
9. "Diğer Belgeler": Sorusturma_Ozet_Raporu (html), Gazete_Haberi (html)""",

        # SİBER SUÇ: Türk Siber Suçlarla Mücadele Dairesi (SSMD) ve Europol EC3 standartları
        "siber_suc": f"""1. "Olay Raporları": Siber_Olay_Bildirim_ve_Tespit_Raporu (html), Guvenlik_Acigi_Teknik_Degerlendirme (html), Sistem_Hasar_ve_Etki_Analizi (html)
2. "Dijital Delil İnceleme": Dijital_Delil_Inceleme_Raporu (html), Disk_ve_Bellek_Adli_Analizi (html), Sifreleme_ve_Kimlik_Dogrulama_Analizi (html), Delil_Ekran_Goruntuleri (image)
3. "Ağ ve İz Analizi": AG_Trafigi_ve_Paket_Analizi (html), IP_Adres_Tespit_ve_WHOIS_Raporu (html), Zararli_Yazilim_Ters_Muhendislik_Raporu (html)
4. "Mağdur Dosyası": Magdur_Profil (html), Veri_Ihlali_Kapsam_ve_Etki_Raporu (html), Maddi_Zarar_Tespiti (html)
5. "Şüpheli Profilleri": Her şüpheli için Supheli_[İsim]_Profili (html) — teknik yetenek, dijital iz AYNEN olsun
6. "İfade Tutanakları": Her şüpheli için Ifade_Tutanagi_[İsim] (audio — saldırı yöntemi ve dijital bağlantıyla)
7. "Tanık Beyanları": Her tanık için Tanik_Ifadesi_[İsim] (audio)
8. "Diğer Belgeler": Sorusturma_Ozet_Raporu (html), BT_Guvenlik_Uzman_Gorusu (html)""",

        "diger": f"""1. "Olay Yeri Tutanakları": Olay_Yeri_Tespit_Tutanagi (html), Olay_Yeri_Fotografi (image)
2. "Mağdur Dosyası": Magdur_Kimlik_ve_Profil (html), Hasar_ve_Zarar_Tespit_Raporu (html), Olay_Kronolojisi (html)
3. "Şüpheli Profilleri": Her şüpheli için Supheli_[İsim]_Profili (html) — yaş, meslek ve motiv AYNEN olsun
4. "İfade Tutanakları": Her şüpheli için Ifade_Tutanagi_[İsim] (audio)
5. "Tanık Beyanları": Her tanık için Tanik_Ifadesi_[İsim] (audio)
6. "Kanıt Arşivi": MOBESE_CCTV_Kaydi (image), Kriminalistik_Delil_Analizi (html), Dijital_Yazisma_Kayitlari (html), Kanit_Fotograflari (image)
7. "Diğer Belgeler": Sorusturma_Ozet_Raporu (html), Gazete_Haberi (html)"""
    }
    crime_categories = crime_category_templates.get(crime, crime_category_templates["diger"])

    prompt = f"""Aşağıdaki dedektiflik vakası için kanıt dosyası listesi oluştur. SADECE JSON array döndür.

ÖNEMLİ: Aşağıdaki vaka bilgilerini BİREBİR kullan. Kendi hikayeni UYDURMA. İsimler, yaşlar, meslekler, mekanlar, tarihler ve olaylar aşağıdakilerle AYNI olmalı.

=== VAKA BİLGİLERİ ===
Başlık: {case_data.get('title', '')}
Dosya No: {case_data.get('case_number', '')}
Suç Türü: {crime}
Soruşturma Birimi: {case_data.get('investigating_unit', '')}
Polis Departmanı: {case_data.get('police_department', '')}
Soruşturmacı: {case_data.get('commissioner_name', '')}

=== MAĞDUR ===
Ad: {victim_name} | Yaş: {victim_age} | Meslek: {victim_occ}
Mağdur Türü: {victim_type}
Olay: {incident_desc}
Tarih: {incident_date} | Saat: {incident_time}
Yer: {incident_loc}

=== ŞÜPHELİLER (İsim, yaş, meslek ve motivi AYNEN kullan) ===
{chr(10).join(suspects_detail)}

=== TANIKLAR ===
{chr(10).join(witnesses_detail)}

=== ZAMAN ÇİZELGESİ ===
{chr(10).join(timeline_text)}

=== ÇÖZÜM (content_summary'lerde İPUCU ver ama doğrudan söyleme) ===
Suçlu: {', '.join(solution.get('culprit_names', []))}
Yöntem: {solution.get('method', '')}

=== DOSYA FORMATI ===
Her dosya bu formatta:
{{"filename": "Dosya_Adi", "display_name": "Görüntü Adı", "category": "Kategori",
  "file_type": "html/image/audio", "content_summary": "5-6 cümle detaylı içerik (YUKARIDAKI VAKA BİLGİLERİYLE TUTARLI)",
  "image_prompt": "", "audio_script": "", "voice": ""}}

file_type kuralları:
- "html": Yazılı belge/rapor. image_prompt/audio_script/voice boş.
- "image": AI fotoğraf. image_prompt İNGİLİZCE detaylı (sahne, ışık, nesneler, açı). audio_script/voice boş.
- "audio": AI ses kaydı. audio_script TÜRKÇE en az 4-5 cümle doğal konuşma. voice: alloy/echo/fable/onyx/nova/shimmer (her kişiye farklı ses).

=== BU VAKANIN SUÇ TÜRÜ: {crime.upper()} ===
Bu suç türüne özgü kategoriler ve dosyalar (AYNEN bu yapıyı kullan, başka kategori ekleme):
{crime_categories}

KONTROL: content_summary'lerde şüphelilerin meslekleri, yaşları, olay yeri, tarihler yukarıdaki verilerle AYNI olmalı.
{"CİNAYET VAKASI: Otopsi, maktul, ölüm nedeni, kan analizi gibi adli tıp terimleri kullanılabilir." if crime == "cinayet" else f"DİKKAT: Bu bir {crime} vakasıdır, CİNAYET DEĞİL! Maktul, otopsi, ölüm nedeni gibi cinayet terimleri KESINLIKLE kullanma. Mağdur, hasar, zarar gibi uygun terimleri kullan."}
En az 20 dosya. En az 4 image, en az 5 audio, geri kalan html."""

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=16384,
                thinking_config=types.ThinkingConfig(thinking_budget=0)
            )
        )
        data = _extract_json(response.text or "")
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and 'evidence_files' in data:
            return data['evidence_files']
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"Gemini evidence files error: {e}")
        return []


def generate_case_content(title, description, setting, difficulty):
    case_data = _generate_case_structure(title, description, setting, difficulty)
    if not case_data:
        return None

    evidence_files = _generate_evidence_files(case_data)
    if not evidence_files:
        print("Warning: Evidence files generation failed, retrying...")
        evidence_files = _generate_evidence_files(case_data)
    case_data['evidence_files'] = evidence_files if evidence_files else []
    return case_data


EVIDENCE_TEMPLATE_CSS = """
:root {
    --primary-color: #1a3a5c;
    --secondary-color: #f2f4f8;
    --alert-color: #c0392b;
    --border-color: #cddae7;
    --accent-gold: #b8860b;
}
body {
    font-family: 'Roboto', sans-serif;
    background-color: #e0e5ec;
    margin: 0;
    padding: 40px 20px;
    color: #333;
    line-height: 1.6;
}
.report-container {
    background-color: #fff;
    max-width: 1000px;
    margin: 0 auto;
    padding: 60px;
    box-shadow: 0 10px 40px rgba(0,0,0,0.15);
    border-top: 8px solid var(--primary-color);
    position: relative;
    overflow: hidden;
}
.watermark {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%) rotate(-35deg);
    font-size: 9rem;
    color: rgba(26, 58, 92, 0.05);
    font-weight: bold;
    text-transform: uppercase;
    pointer-events: none;
    z-index: 0;
    letter-spacing: 20px;
}
.confidential-stamp {
    position: absolute;
    top: 80px;
    right: 60px;
    border: 4px solid var(--alert-color);
    color: var(--alert-color);
    padding: 8px 20px;
    font-size: 1.1rem;
    font-weight: 700;
    transform: rotate(12deg);
    opacity: 0.7;
    z-index: 2;
    letter-spacing: 3px;
}
.handwritten {
    font-family: 'Caveat', cursive;
    color: #0033cc;
    font-size: 1.25rem;
    font-weight: 600;
}
.handwritten-alert {
    font-family: 'Caveat', cursive;
    color: var(--alert-color);
    font-size: 1.3rem;
    font-weight: 700;
}
.handwritten-note-box {
    font-family: 'Caveat', cursive;
    background-color: #fffde7;
    border: 1px dashed #f9a825;
    padding: 15px 20px;
    margin: 15px 0;
    font-size: 1.35rem;
    line-height: 1.8;
    color: #1a237e;
    position: relative;
    z-index: 1;
}
.handwritten-note-box.alert {
    background-color: #ffebee;
    border-color: var(--alert-color);
    color: var(--alert-color);
}
.handwritten-note-label {
    font-family: 'Roboto', sans-serif;
    font-size: 0.7rem;
    color: #999;
    text-transform: uppercase;
    letter-spacing: 1px;
    display: block;
    margin-bottom: 5px;
}
h1, h2, h3, h4 {
    font-family: 'Roboto Condensed', 'Roboto', sans-serif;
    margin-top: 0;
}
.main-header {
    text-align: center;
    border-bottom: 3px double var(--primary-color);
    padding-bottom: 20px;
    margin-bottom: 30px;
    position: relative;
    z-index: 1;
}
.institution-info {
    font-size: 1.4rem;
    font-weight: 700;
    color: var(--primary-color);
    text-transform: uppercase;
    letter-spacing: 2px;
}
.institution-sub {
    font-size: 1rem;
    color: #555;
    margin-top: 5px;
    text-transform: uppercase;
    letter-spacing: 1px;
}
.section-block {
    margin-bottom: 30px;
    position: relative;
    z-index: 1;
}
.section-title {
    background-color: var(--primary-color);
    color: #fff;
    padding: 8px 15px;
    font-size: 1.05rem;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 15px;
    display: flex;
    align-items: center;
}
.section-title::before {
    content: '■';
    margin-right: 10px;
    font-size: 0.8rem;
    color: #90caf9;
}
.data-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.93rem;
}
.data-table th, .data-table td {
    border: 1px solid var(--border-color);
    padding: 10px;
    vertical-align: top;
}
.data-table th {
    background-color: var(--secondary-color);
    color: var(--primary-color);
    text-align: left;
    width: 25%;
    font-weight: 700;
}
.result-critical {
    background-color: #ffebee;
    color: var(--alert-color);
    font-weight: bold;
}
.report-meta-bar {
    display: flex;
    justify-content: space-between;
    background-color: var(--secondary-color);
    padding: 12px 20px;
    border: 1px solid var(--border-color);
    font-weight: 600;
    font-size: 0.85rem;
    margin-bottom: 25px;
    position: relative;
    z-index: 1;
}
.footer-signatures {
    display: flex;
    justify-content: space-between;
    margin-top: 40px;
    padding-top: 20px;
    border-top: 2px solid var(--border-color);
    position: relative;
    z-index: 1;
}
.signature-block {
    text-align: center;
    width: 30%;
}
.signature-line {
    border-top: 1px solid #333;
    margin-top: 50px;
    padding-top: 5px;
    font-size: 0.85rem;
    font-weight: 600;
}
@media print {
    body { padding: 0; background: white; }
    .report-container { box-shadow: none; padding: 30px; }
}
"""


def generate_evidence_html(case_data, evidence_file):
    victim = case_data.get("victim", {})
    suspects = case_data.get("suspects", [])
    timeline = case_data.get("timeline", [])
    witnesses = case_data.get("witnesses", [])
    solution = case_data.get("solution", {})
    crime_type = case_data.get("crime_type", "cinayet")
    victim_type = victim.get("victim_type", "maktul" if crime_type == "cinayet" else "magdur")

    crime_type_labels = {
        "cinayet": "Cinayet Soruşturması",
        "hirsizlik": "Hırsızlık/Soygun Soruşturması",
        "dolandiricilik": "Dolandırıcılık/Sahtecilik Soruşturması",
        "kayip_kisi": "Kayıp Kişi Soruşturması",
        "kacakcilik": "Kaçakçılık Soruşturması",
        "sabotaj": "Sabotaj/Casusluk Soruşturması",
        "kundaklama": "Kundaklama Soruşturması",
        "siber_suc": "Siber Suç Soruşturması",
        "diger": "Cezai Soruşturma"
    }
    crime_label = crime_type_labels.get(crime_type, "Cezai Soruşturma")

    victim_info_lines = f"""Ad: {victim.get('name', '')}
Yaş: {victim.get('age', '')}
Meslek: {victim.get('occupation', '')}
Mağdur Türü: {victim_type}
Olay Açıklaması: {victim.get('incident_description', victim.get('death_cause', ''))}
Olay Tarihi: {victim.get('incident_date', victim.get('death_date', ''))}
Olay Saati: {victim.get('incident_time', victim.get('death_time', ''))}
Olay Yeri: {victim.get('incident_location', victim.get('death_location', ''))}
Geçmiş: {victim.get('background', '')}"""

    prompt = f"""Sen profesyonel bir adli belge tasarımcısısın. Bir {crime_label} oyunu için gerçekçi bir HTML kanıt dosyası oluşturacaksın.

SUÇ TÜRÜ: {crime_label}
(Bu bir {crime_type} vakasıdır. {"Maktul var, otopsi ve ölüm bilgileri geçerlidir." if crime_type == "cinayet" else "Bu bir cinayet davası DEĞİLDİR! Maktul, otopsi, ölüm nedeni gibi terimler KULLANMA. Bunun yerine mağdur, olay raporu, zarar tespiti gibi uygun terimleri kullan."})

VAKA BİLGİLERİ:
Vaka Başlığı: {case_data.get('title', '')}
Dosya No: {case_data.get('case_number', '2026/001')}
Soruşturma Birimi: {case_data.get('investigating_unit', case_data.get('police_department', ''))}
Emniyet: {case_data.get('police_department', '')}
Soruşturmacı: {case_data.get('commissioner_name', '')}

MAĞDUR BİLGİLERİ:
{victim_info_lines}

ŞÜPHELİLER:
{json.dumps(suspects, ensure_ascii=False, indent=2)}

TANIKLAR:
{json.dumps(witnesses, ensure_ascii=False, indent=2)}

ZAMAN ÇİZELGESİ:
{json.dumps(timeline, ensure_ascii=False, indent=2)}

OLUŞTURULACAK DOSYA:
Dosya Adı: {evidence_file.get('display_name', '')}
Kategori: {evidence_file.get('category', '')}
İçerik Detayı: {evidence_file.get('content_summary', '')}

TASARIM KURALLARI:
1. Tam bir HTML belgesi oluştur (<!DOCTYPE html> ile başla)
2. Tüm CSS inline <style> tagı içinde olsun
3. Google Fonts kullan: 'Roboto', 'Roboto Condensed', 'Caveat'
4. Renk paleti: Lacivert (#1a3a5c), Beyaz arkaplan, Kırmızı uyarılar (#c0392b), Altın vurgu (#b8860b)
5. "GİZLİ" filigranı (watermark) ekle - yarı saydam, döndürülmüş
6. "GİZLİ" damgası (confidential-stamp) sağ üstte
7. Gerçekçi Türk polis/emniyet formatına uygun olsun - suç türüne göre ilgili birim başlığı kullan
8. Belgede resmi kurum başlığı, dosya numarası, tarih, sayı bilgileri olsun
9. Dedektif el yazısı notları ekle (Caveat fontu, mavi veya kırmızı)
10. Sarı not kutuları (handwritten-note-box) ile gizli ipuçları ekle
11. Tablolar, bölüm başlıkları, alt bilgi ve imza alanları olsun
12. En az 400 satır HTML oluştur - ÇOK DETAYLI ve UZUN bir belge olsun
13. Her bilgi diğer kanıtlarla tutarlı olsun
14. Belge sonunda imza blokları ve resmi mühür alanı olsun

DOSYA TÜRÜNE GÖRE ÖZEL İÇERİK (Türkiye ve uluslararası polis standartlarına göre):

CİNAYET VAKALARI (Adli Tıp Kurumu + Emniyet Müdürlüğü):
- Ölüm Tutanağı: Ölüm tespit yeri, saati, ilk müdahale ekibi bilgileri
- Otopsi Raporu: Dış muayene bulguları, iç muayene, histopatoloji, ölüm nedeni ve şekli (ani/doğal/intihar/cinayet), tahmini ölüm saati (post-mortem interval)
- Adli Tıp Kurumu Raporu: Uzman hekim imzalı, resmi ATK formatı, bölüm kodları
- Toksikoloji Analizi: Kan, idrar, mide içeriği örneklerinde ilaç/zehir/alkol taraması
- DNA ve Seroloji Analizi: Kan grubu, DNA profili, örnek lokasyonları, eşleştirme sonuçları
- Balistik ve Kriminalistik İnceleme: Ateşli silah izi, mermi, kovan, atış mesafesi analizi (silah varsa)
- Telefon HTS Kayıtları: Arama/mesaj detayları, baz istasyonu konum verileri (operatörden alınan resmi belge)

HIRSIZLIK/SOYGUN (Emniyet — Hırsızlık Büro Amirliği):
- Hırsızlık Olayı Tespit Tutanağı: Olay yeri tespiti, ilk müdahale saati, kırma/delme izleri
- Çalınan Mal Tespit Tutanağı: Her eşyanın markası, modeli, seri numarası, tahmini değeri, adet
- Zorla Giriş ve Kırık İz İnceleme Raporu: Kilit/menteşe/pencere hasarı, alet izi kalıpları
- Parmak İzi ve Biyometrik Raporu: Latent iz tespiti, AFIS sorgu sonucu, eşleştirme
- Güvenlik Sistemi Analizi: Alarm log dökümü, kamera kör noktaları, devre dışı bırakma yöntemi
- MOBESE/CCTV Görüntü Dökümü: Zaman damgalı kare listesi, plaka/yüz tespiti
- Telefon HTS Analizi: Olay öncesi/sonrası bölgede aktif hatlar

DOLANDIRICILIK (MASAK — Mali Suçları Araştırma Kurulu + Emniyet):
- Suç Duyurusu ve Olay Tespiti: Şikayetçi beyanı, şikayet tarihi, iddia özeti
- Kriminalistik Belge İnceleme Raporu: Sahte imza karşılaştırması, mürekkep/kağıt analizi, mühür doğrulama
- Mali İnceleme Bilirkişi Raporu: Dolandırıcılık miktarı, hesap hareketleri tablosu, zarar tespiti
- Banka Hesap Dökümü ve EFT Kayıtları: Tarih/saat/tutar/alıcı bilgili resmi banka yazısı
- Para Akışı ve Sermaye Hareketi Analizi (MASAK): Şüpheli işlemler, kara para aklama göstergeleri
- Sahte Sözleşme ve Evrak İncelemesi: Belge özellikleri, çelişen tarihler, sahtecilik kanıtları
- Dijital Yazışma ve E-Posta Kayıtları: Header analizi, IP adresi, gönderim saati, içerik

KAYIP KİŞİ (Emniyet — Kayıp Kişiler Bürosu):
- Kayıp Kişi Müracaat Formu: Müracaatçı bilgileri, kayıp tarihi/saati/yeri, giydiği kıyafetler
- Kimlik ve Fiziksel Tanımlama Formu: Boy, kilo, saç/göz rengi, özel işaretler, diş kaydı
- Kişisel Eşya ve Son Bulunan Eşyalar Listesi: Telefon, cüzdan, anahtar durumu
- Sağlık Bilgileri ve Özel Notlar: Kronik hastalık, ilaç, psikolojik geçmiş, intihar riski
- Son Bilinen Aktivite Kayıtları: ATM kullanımı, telefon aktivitesi, sosyal medya, son görüşmeler
- MOBESE Son Görülen An Kaydı: Zaman damgalı kamera dökümü, giysi ve yön tespiti
- Telefon HTS ve Konum Analizi: Son arama/mesaj, baz istasyonu hareketi

KAÇAKÇILIK (KOM Dairesi — Kaçakçılık ve Organize Suç + Gümrük):
- Müsadere Tutanağı (CMK 127): Yasal dayanak, el koyma yeri/saati, el koyan yetkili, imzalar
- Müsadere Edilen Eşya Listesi: Türü, miktarı, tahmini değeri, menşei, seri/parti no
- Gümrük İdarî İşlem Tutanağı: Beyan/gerçek içerik farkı, gümrük kaçağı tespiti
- Telekomünikasyon Tespit Tutanağı (CMK 135): Mahkeme kararı tarihi, tespit edilen görüşmeler
- Fiziki Takip ve Gözlem Tutanağı: Tarih/saat/yer, araç/plaka, hareket güzergahı
- Güzergah ve Hareket Analizi: Geçiş noktaları, sınır kapısı kayıtları, yakıt/konaklama
- Organize Suç Ağı Analizi: Hiyerarşi şeması, üye rolleri, bağlantı haritası

SABOTAJ/CASUSLUK (Jandarma İstihbarat + Emniyet KOM):
- Sabotaj Tespit ve Olay Raporu: İlk müdahale, güvenlik ihlal noktası, modus operandi
- Teknik Hasar Tespit Raporu: Bilirkişi tarafından hazırlanmış, hasar türü ve yöntemi
- Mali Zarar Tespiti Raporu: Tahmini üretim kaybı, onarım maliyeti, doğrudan/dolaylı zarar
- Sistem Erişim Logları ve Yetkisiz Giriş Tutanağı: Kart/biometrik/şifre giriş-çıkış kayıtları
- Güvenlik Açığı Değerlendirme Raporu: Nasıl ihlal edildi, hangi önlemler atlatıldı
- Teknik Uzman Bilirkişi Raporu: Kasıtlı mı/kaza mı tespiti, yöntem analizi
- İç Yazışma ve E-Posta Tespiti: Kısıtlı bilgiye erişim, bilgi sızdırma kanıtları

KUNDAKLAMA (İtfaiye + Adli Tıp + NFPA 921 standardı):
- Yangın Olay Yeri Tespit Tutanağı: İlk ihbar saati, müdahale saati, söndürme yöntemi
- İtfaiye Müdahale ve Sonuç Tutanağı: Ekip bilgileri, su kullanımı, kurtarılan değerler
- Yangın Orijin ve Neden Analizi (NFPA 921): Yanma modeli, en yüksek ısı noktası (origin), ateşleme kaynağı, kasıt tespiti
- Yanık İz ve Yanma Modeli Raporu: V-pattern, alev yayılım yönü, ivmelenme noktaları
- Kimyasal Hızlandırıcı Tespit Analizi (GC-MS): Benzin/tiner/alkol kalıntısı laboratuvar sonucu
- Parmak İzi ve DNA Analizi: Yangın artığında bulunan biyolojik materyaller
- Hasar Tespit ve Değerleme Raporu: Yapısal hasar, taşınır mal kaybı, toplam maddi zarar
- Sigortacı Hasar Tespit Belgesi: Sigorta şirketinin talep/red kararı ve poliçe bilgileri

SİBER SUÇ (Türk Siber Suçlarla Mücadele Dairesi — SSMD + Europol EC3 standardı):
- Siber Olay Bildirim ve Tespit Raporu: Saldırı türü (DDoS/phishing/ransomware vb.), etkilenen sistemler, keşif zamanı
- Dijital Delil İnceleme Raporu (SSMD): Disk imajı hash değerleri, zincir muhafaza kaydı, inceleme metodolojisi
- Disk ve Bellek Adli Analizi: Silinmiş/gizlenmiş dosyalar, tarayıcı geçmişi, sistem logları
- Ağ Trafiği ve Paket Analizi: Wireshark/PCAP dökümü, anormal trafik örüntüleri, C2 sunucu iletişimi
- IP Adres Tespit ve WHOIS Raporu: Saldırı kaynağı IP'leri, ASN/ISP bilgisi, coğrafi konum
- Zararlı Yazılım Ters Mühendislik Raporu: Malware davranışı, imzası, yaratıcı ipuçları
- Veri İhlali Kapsam ve Etki Raporu: Sızdırılan veri türü ve miktarı, etkilenen kullanıcı sayısı
- BT Güvenlik Uzman Görüşü: Güvenlik açığının teknik analizi, yama önerileri

TÜM SUÇ TÜRLERİ İÇİN ORTAK STANDARTLAR:
- Şüpheli Profili: TC kimlik, sabıka kaydı, ilişki ağı diyagramı, mali durum, motivasyon analizi — resmi Emniyet formatı
- İfade Tutanağı: CMK uyarınca hazırlanmış, haklarını bildirir şerhi, avukat varlığı, soru-cevap
- Tanık Beyanı: Tanığın kimliği, gözlem koşulları, çapraz doğrulama notu, imza ve tarih
- MOBESE/CCTV Dökümü: Kamera lokasyonu, zaman damgası, görüntü kalitesi değerlendirmesi
- HTS Kayıtları: Operatörden gelen resmi yazı, hat sahibi kimliği, arama/mesaj detayları

Sadece HTML kodu döndür, başka açıklama yazma."""

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=32768,
                thinking_config=types.ThinkingConfig(thinking_budget=0)
            )
        )
        content = response.text or ""
        if not content:
            return None
        if content.startswith("```html"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        return content.strip()
    except Exception as e:
        print(f"Gemini evidence generation error: {e}")
        return None


def generate_success_file(case_data):
    victim = case_data.get("victim", {})
    suspects = case_data.get("suspects", [])
    solution = case_data.get("solution", {})
    timeline = case_data.get("timeline", [])
    crime_type = case_data.get("crime_type", "cinayet")

    culprits = [s for s in suspects if s.get("is_culprit")]
    innocents = [s for s in suspects if not s.get("is_culprit")]

    crime_type_labels = {
        "cinayet": "Cinayet",
        "hirsizlik": "Hırsızlık/Soygun",
        "dolandiricilik": "Dolandırıcılık",
        "kayip_kisi": "Kayıp Kişi",
        "kacakcilik": "Kaçakçılık",
        "sabotaj": "Sabotaj",
        "kundaklama": "Kundaklama",
        "siber_suc": "Siber Suç",
        "diger": "Suç"
    }
    crime_label = crime_type_labels.get(crime_type, "Suç")

    victim_type = victim.get("victim_type", "maktul" if crime_type == "cinayet" else "magdur")
    victim_line = f"{'MAKTUL' if victim_type == 'maktul' else 'MAĞDUR'}: {victim.get('name', '')} ({victim.get('age', '')}), {victim.get('occupation', '')}"
    incident_line = f"Olay: {victim.get('incident_description', victim.get('death_cause', ''))} - {victim.get('incident_date', victim.get('death_date', ''))} {victim.get('incident_time', victim.get('death_time', ''))}"
    location_line = f"Yer: {victim.get('incident_location', victim.get('death_location', ''))}"

    prompt = f"""Sen profesyonel bir adli belge tasarımcısısın. Bir dedektiflik gizemi oyununun BAŞARI DOSYASI'nı (çözüm sayfası) oluştur.

SUÇ TÜRÜ: {crime_label}
{"Bu bir cinayet vakasıdır." if crime_type == "cinayet" else f"Bu bir {crime_label} vakasıdır, cinayet DEĞİLDİR! Maktul, otopsi, cinayet yöntemi gibi terimler kullanma. Bunun yerine mağdur, suç yöntemi, olay açıklaması gibi uygun terimler kullan."}

VAKA:
Başlık: {case_data.get('title', '')}
Dosya No: {case_data.get('case_number', '')}

{victim_line}
{incident_line}
{location_line}

SUÇLULAR:
{json.dumps(culprits, ensure_ascii=False, indent=2)}

MASUM ŞÜPHELİLER:
{json.dumps(innocents, ensure_ascii=False, indent=2)}

ÇÖZÜM:
{json.dumps(solution, ensure_ascii=False, indent=2)}

ZAMAN ÇİZELGESİ:
{json.dumps(timeline, ensure_ascii=False, indent=2)}

TASARIM:
1. Koyu lacivert arka plan (#0a1929), altın (#ffc107) başlıklar
2. Büyük "VAKA ÇÖZÜLDÜ" başlığı
3. Suçluların tam profili ve motivasyonları
4. {"Cinayet yöntemi" if crime_type == "cinayet" else "Suç yöntemi"} detaylı açıklaması
5. Masum şüphelilerin neden masum olduğu
6. Tam zaman çizelgesi
7. Kilit ipuçları bölümü
8. En az 350 satır HTML
9. Google Fonts: 'Roboto', 'Roboto Condensed', 'Caveat'
10. Tüm CSS inline

Sadece HTML kodu döndür."""

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=32768,
                thinking_config=types.ThinkingConfig(thinking_budget=0)
            )
        )
        content = response.text or ""
        if not content:
            return None
        if content.startswith("```html"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        return content.strip()
    except Exception as e:
        print(f"Gemini success file error: {e}")
        return None


def generate_case_cover_image(case_data):
    """Generate a cinematic cover image for the case card/thumbnail."""
    title = case_data.get('title', '')
    crime_type = case_data.get('crime_type', 'cinayet')
    setting = case_data.get('setting', '')

    crime_scene_map = {
        'cinayet': 'dark crime scene with police tape, forensic markers, dramatic shadows, detective investigation atmosphere',
        'hirsizlik': 'dramatic robbery aftermath, broken display case or vault, scattered clues, dark moody lighting',
        'dolandiricilik': 'shadowy financial fraud scene, scattered documents and contracts, dim office lighting, suspicious atmosphere',
        'kayip_kisi': 'mysterious empty room with personal belongings left behind, dim light through window, eerie silence',
        'kacakcilik': 'night-time smuggling scene, warehouse or dock, crates, torch beams, tense atmosphere',
        'sabotaj': 'industrial sabotage aftermath, damaged machinery or server room, warning lights, dark atmosphere',
        'kundaklama': 'fire investigation scene, charred debris, smoke haze, forensic team silhouettes',
        'siber_suc': 'cybercrime hacker den, multiple dark monitors with code, dramatic blue glow, shadowy figure',
        'diger': 'mysterious crime scene, dark noir atmosphere, dramatic lighting, police investigation',
    }
    crime_desc = crime_scene_map.get(crime_type, crime_scene_map['diger'])

    prompt = (
        f"Cinematic Turkish detective mystery game cover art. "
        f"{crime_desc}. "
        f"Setting: {setting[:120]}. "
        "Dark noir atmosphere, dramatic high-contrast lighting, photorealistic, "
        "no visible human faces, no text, no logos, moody and suspenseful, "
        "professional game cover composition, wide shot."
    )

    try:
        response = openai_client.images.generate(
            model="gpt-image-1",
            prompt=prompt,
            size="1024x1024",
        )
        image_base64 = response.data[0].b64_json or ""
        return base64.b64decode(image_base64)
    except Exception as e:
        print(f"Cover image generation error: {e}")
        return None


def generate_evidence_image(case_data, evidence_file):
    title = case_data.get('title', '')
    crime_type = case_data.get('crime_type', 'cinayet')
    victim = case_data.get('victim', {})
    display_name = evidence_file.get('display_name', '')
    content_summary = evidence_file.get('content_summary', '')
    category = evidence_file.get('category', '')
    image_prompt = evidence_file.get('image_prompt', '')

    if image_prompt:
        prompt = image_prompt
    else:
        prompt = f"Forensic crime scene evidence photograph for a detective mystery case. "
        prompt += f"Case: {title}. Crime type: {crime_type}. "
        prompt += f"Evidence: {display_name}. {content_summary}. "
        prompt += f"Category: {category}. "

        if 'olay_yeri' in display_name.lower() or 'olay yeri' in display_name.lower():
            prompt += "Dark atmospheric crime scene with evidence markers, police tape, dim lighting. "
        elif 'otopsi' in display_name.lower() or 'maktul' in display_name.lower():
            prompt += "Medical forensic document style, clinical examination setting, medical equipment. "
        elif 'supheli' in display_name.lower() or 'şüpheli' in display_name.lower():
            prompt += "Police mugshot style portrait photograph, neutral background, front-facing. "
        elif 'kanit' in display_name.lower() or 'kanıt' in display_name.lower():
            prompt += "Close-up forensic evidence photograph with measurement scale, evidence marker, labeled. "
        elif 'harita' in display_name.lower() or 'kroki' in display_name.lower():
            prompt += "Overhead map or floor plan with marked locations, police investigation style. "
        else:
            prompt += "Realistic forensic investigation photograph, dark moody lighting. "

        prompt += "Photorealistic style, dramatic lighting, no text overlay."

    try:
        response = openai_client.images.generate(
            model="gpt-image-1",
            prompt=prompt,
            size="1024x1024",
        )
        image_base64 = response.data[0].b64_json or ""
        return base64.b64decode(image_base64)
    except Exception as e:
        print(f"OpenAI image generation error ({display_name}): {e}")
        return None


AUDIO_VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]

def generate_evidence_audio(case_data, evidence_file):
    title = case_data.get('title', '')
    display_name = evidence_file.get('display_name', '')
    content_summary = evidence_file.get('content_summary', '')
    audio_script = evidence_file.get('audio_script', '')
    voice = evidence_file.get('voice', 'onyx')

    if voice not in AUDIO_VOICES:
        voice = 'onyx'

    if not audio_script:
        audio_script = content_summary

    if not audio_script:
        return None

    try:
        response = openai_client.chat.completions.create(
            model="gpt-audio",
            modalities=["text", "audio"],
            audio={"voice": voice, "format": "mp3"},
            messages=[
                {"role": "system", "content": "Sen bir Türk polis soruşturması ses kaydı simülatörüsün. Verilen metni doğal bir şekilde, sanki gerçek bir ifade kaydıymış gibi oku. Türkçe konuş."},
                {"role": "user", "content": f"Aşağıdaki metni aynen ve doğal bir şekilde seslendir:\n\n{audio_script}"},
            ],
        )
        audio_data = getattr(response.choices[0].message, "audio", None)
        if audio_data and hasattr(audio_data, "data"):
            return base64.b64decode(audio_data.data)
        return None
    except Exception as e:
        print(f"OpenAI audio generation error ({display_name}): {e}")
        return None
