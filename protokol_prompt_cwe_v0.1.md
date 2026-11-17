# Protokol Penelitian v0.1 — Prompt Berbasis Kriteria CWE

**Status:** draf pra-pilot untuk diskusi pembimbing. **Belum ada hasil eksperimen.** Disusun setelah matriks literatur awal L1–L8 di `literature_matrix_prompt_cwe.md`. Tanggal/versi/model/dataset belum dikunci. Jangan memakai data uji akhir untuk memilih prompt.

## 1. Judul kerja dan posisi penelitian

**Judul kerja yang lebih spesifik:** *Evaluasi Kontribusi Kriteria Operasional CWE dan Bukti Kode dalam Prompt terhadap Deteksi Kerentanan oleh Large Language Model.*

Judul sebelumnya terlalu umum: studi terdahulu sudah membandingkan prompt dasar dengan prompt yang menyebut tipe CWE (Lu dkk., 2026, arXiv:2602.06687); optimasi prompt lintas-CWE juga sudah ada (Xie dkk., 2026, DOI:10.3390/info17080762). Kontribusi yang diuji di sini **bukan** “pertama menggunakan CWE”, melainkan apakah menambahkan **kriteria operasional dan kewajiban bukti kode** di atas nama CWE mengubah kinerja klasifikasi dan kualitas alasan pada desain terkontrol. Ini masih **hipotesis gap**, bukan klaim kebaruan final.

## 2. Pertanyaan penelitian & hipotesis

- **RQ1 (primer):** Pada kode dan informasi CWE yang sama, berapa perubahan kualitas klasifikasi ketika prompt yang hanya menyebut CWE (P1) diganti prompt berkriteria operasional + bukti kode (P2)?
- **RQ2:** Bagaimana perubahan false positive dan false negative, termasuk pada pasangan kode rentan–patched jika tersedia?
- **RQ3:** Apakah bukti yang ditunjuk model sesuai dengan kode, dan berapa konsekuensi token, waktu, serta biaya?
- **H0:** Pada populasi kasus uji yang didefinisikan, P1 dan P2 memiliki kinerja setara dalam metrik primer.
- **H1:** Kinerja P1 dan P2 berbeda. Arah perubahan harus dilaporkan apa adanya; P2 **tidak dijamin** lebih baik.

## 3. Ruang lingkup dan unit analisis

- **Bahasa:** satu bahasa saja; **TBD setelah seleksi dataset**. Hindari campuran C/C++ dan Java dalam analisis utama.
- **Jenis kelemahan:** satu CWE pada pilot; perluas ke CWE kedua hanya jika label, sampel positif-negatif, dan waktu mencukupi. Definisi/kriteria wajib diambil dari sumber CWE resmi dan dicatat versinya.
- **Unit pengamatan:** satu *kasus kode* (cuplikan beserta konteks tetap) × satu kondisi prompt. Semua kondisi melihat kode yang identik. Jika sampel berasal dari pasangan vulnerable–patched atau proyek sama, tandai `pair_id`/`project_id` agar tidak dihitung sebagai kasus independen semu.
- **Tugas utama:** klasifikasi biner `vulnerable`/`not_vulnerable` **terhadap CWE yang diberitahukan**. Ini deteksi *conditioned on a known CWE*, bukan pencarian semua kerentanan yang belum diketahui. Jangan mengirim label benar atau status patched ke model.
- **Target inferensi:** pada dataset, bahasa, CWE, konteks, dan model yang diuji; bukan klaim umum untuk seluruh repositori produksi.

## 4. Pemilihan data (semua TBD sampai audit nyata)

Kandidat awal untuk diperiksa: PrimeVul, DiverseVul, atau VulDetectBench; belum diputuskan dan belum diunduh/diaudit untuk studi ini. Catat lisensi, format, repositori/commit, bahasa, `CWE_id`, label, apakah ada pasangan perbaikan, dan ketersediaan konteks kode. Jangan mencampur benchmark dengan skema label berbeda tanpa pemetaan yang dapat dijustifikasi.

**Syarat inklusi:** kode bisa dibaca; label biner dan CWE dapat ditelusuri; ada konteks cukup untuk keputusan; lisensi penggunaan jelas; tersedia sampel positif dan negatif. **Eksklusi:** duplikat dekat tanpa penanganan, kode terpotong kritis, label/CWE ambigu yang tak dapat diselesaikan, sampel yang butuh data eksternal tidak tersedia. Simpan jumlah awal, alasan eksklusi, dan ID kasus; jangan memilih hanya kasus yang berhasil dijawab model.

**Pemisahan:** data pengembangan untuk menyusun prompt/aturan parser dan data uji akhir untuk evaluasi sekali setelah protokol dibekukan. Jika ada pasangan atau beberapa sampel satu proyek, lakukan pemisahan berdasarkan `pair_id`/`project_id`, bukan baris acak. Laporkan potensi kontaminasi pretraining LLM yang tidak dapat dibuktikan hilang sepenuhnya.

## 5. Kondisi perlakuan — prompt v0.1 (masih template)

Semua kondisi menggunakan **model/versi, pesan sistem, kode, konteks, pengaturan API, dan format JSON yang sama**. Perbedaan P1/P2 hanya *instruksi kriteria*; jika P2 lebih panjang, biaya token adalah konsekuensi perlakuan yang dilaporkan. Definisi CWE spesifik baru diisi setelah CWE dipilih, dan harus konsisten untuk seluruh kasus.

**Instruksi umum tetap untuk P1/P2:**
> Analisis kode di bawah hanya untuk kelemahan yang ditentukan. Jangan mengasumsikan fungsi/proses lain yang tidak ditampilkan. Jawab dalam JSON valid berisi `decision` (`vulnerable` atau `not_vulnerable`), `evidence` (kutipan singkat atau lokasi baris dalam kode yang tersedia; boleh kosong jika tidak ada bukti), dan `reason` (maksimal dua kalimat). Bila konteks tidak cukup untuk menyimpulkan, gunakan `not_vulnerable` dan tandai `insufficient_context: true`; kasus ini akan dilaporkan terpisah, bukan disembunyikan.

**P1 — pembanding CWE-name:**
> Target pemeriksaan: `[CWE_ID] — [NAMA_RESMI_CWE]`. Tentukan apakah kode memenuhi kelemahan tersebut. Kode: `[KODE_DAN_KONTEKS_IDENTIK]`.

**P2 — kriteria + bukti:**
> Target pemeriksaan: `[CWE_ID] — [NAMA_RESMI_CWE]`. Kriteria operasional resmi yang relevan: `[DEFINISI_SINGKAT_CWE]`; `[INDIKATOR_YANG_HARUS_TERLIHAT]`; `[KONDISI_YANG_MENYANGKAL_ATAU_MEMITIGASI]`. Nyatakan `vulnerable` hanya bila alur/bukti pada kode yang terlihat memenuhi kriteria; sertakan lokasi bukti dan jelaskan hubungan sebab-akibat. Jika mitigasi tampak atau bukti tidak cukup, tandai sesuai aturan keluaran tetap. Kode: `[KODE_DAN_KONTEKS_IDENTIK]`.

**P0 opsional:** kode + pertanyaan kerentanan umum tanpa target CWE. P0 **bukan** pembanding utama karena jenis tugasnya berbeda; laporkan pada bagian eksploratif terpisah jika budget memungkinkan. Hindari memasukkan contoh berlabel/few-shot ke salah satu kondisi saja.

**Catatan validitas:** aturan `insufficient_context -> not_vulnerable` di atas dapat menghasilkan FN sistematis; keputusan ini akan ditinjau saat pilot dan dibekukan sebelum uji akhir. Metrik cakupan/abstention dilaporkan terpisah bila perlu. Jangan menyamakan `not_vulnerable` dengan bukti keamanan mutlak.

## 6. Desain eksperimen dan pelaksanaan

1. Audit dataset dan tentukan unit/split. Catat hash dataset, versi sumber, daftar kasus, serta alasan inklusi/eksklusi.
2. Gunakan data pengembangan untuk memeriksa parsing, panjang konteks, konsistensi P1/P2, biaya, dan kelayakan penilaian bukti. Jangan hitung pilot sebagai hasil akhir.
3. Bekukan versi prompt, model/API, pengaturan sampling (misalnya temperatur rendah, bila didukung), definisi CWE, parser, aturan invalid/timeout, dan metrik **sebelum** membuka data uji.
4. Jalankan P1 dan P2 pada **kasus uji yang sama**. Imbangi/acak urutan P1/P2 per kasus dengan seed tersimpan agar waktu layanan tidak selalu berimpit dengan satu kondisi. Catat request ID, waktu, versi model aktual, respons mentah, pemakaian token, dan latensi.
5. Jika API berubah/terputus, jangan gabungkan batch berbeda diam-diam; dokumentasikan dan analisis sensitivitas. Retry hanya untuk gangguan teknis yang ditentukan sebelumnya; respons tidak valid dicatat, bukan dihapus.
6. Reviewer menilai bukti pada sampel discordant dan sampel acak menggunakan rubrik yang dibuat sebelum melihat hasil; jika memungkinkan, sembunyikan identitas P1/P2 saat penilaian.
7. Simpan kode evaluasi, konfigurasi, split, dan agregat anonim agar eksperimen dapat diulang dalam batas lisensi dataset dan kebijakan API.

## 7. Output dan metrik

**Skema per panggilan:** `sample_id`, `pair_id`, `project_id`, `language`, `CWE_id`, `true_label`, `prompt_condition`, `prompt_version`, `model_version`, `seed/order`, `raw_response`, `predicted_label`, `insufficient_context`, `parse_status`, `evidence`, `reason`, `input_tokens`, `output_tokens`, `latency_ms`, `estimated_cost`, `timestamp`, `error`.

**Primer:** F1 untuk kelas `vulnerable` dan selisih P2−P1 pada unit evaluasi yang sama; tampilkan precision, recall, confusion matrix, FP dan FN agar peningkatan F1 tidak menutupi trade-off. Laporkan invalid output rate dan kasus insufficient context secara eksplisit. Jika prevalensi dataset sengaja diimbangi, jangan menafsirkan precision sebagai performa populasi produksi.

**Sekunder:** validitas bukti berdasarkan rubrik manual (bukti benar, bukti salah/tidak relevan, tidak ada bukti, label ambigu), token, latensi, dan biaya per kasus. Statistik perbedaan berpasangan/interval ketidakpastian dapat memakai bootstrap pada **kelompok independen** (proyek/pasangan), bukan menganggap dua prompt atau dua sisi pasangan sebagai sampel independen. Uji statistik spesifik dikunci setelah struktur data diketahui; jangan p-hack.

## 8. Kriteria kelayakan pilot & batas biaya

Pilot berhasil bila dapat dibuktikan: kode dan label masuk akal; P1/P2 dapat dijalankan dan di-parse dengan aturan tetap; kasus positif/negatif tersedia; sumber definisi CWE jelas; output bukti bisa dinilai; tidak ada kebocoran split yang terang; estimasi token/biaya masuk batas yang disetujui. Kegagalan pilot berarti **revisi protokol dan judul bila perlu**, bukan menciptakan hasil.

**Biaya belum dihitung** karena jumlah kasus, provider/model, tarif, dan panjang konteks belum dipilih. Rumus: `total = Σ[(input_tokens/1.000.000 × tarif_input) + (output_tokens/1.000.000 × tarif_output)]` untuk seluruh panggilan, ditambah buffer retry/pilot yang dicatat. Pastikan apakah anggaran Rp500 ribu–Rp1 juta adalah total atau per bulan sebelum menetapkan ukuran studi.

## 9. Keputusan terbuka untuk pembimbing (wajib sebelum eksperimen utama)

- Bahasa + CWE spesifik beserta definisi resmi dan versi.
- Dataset tunggal, lisensi, label positif-negatif, konteks, dan strategi split kelompok.
- Model tunggal, snapshot/version yang stabil, tarif dan ketersediaan API; VPS untuk orkestrasi, bukan asumsi bahwa model besar dijalankan lokal.
- Ukuran sampel ditentukan dari ketersediaan unit independen dan presisi yang diinginkan, bukan angka arbitrer.
- Aturan abstention/insufficient context dan keluaran invalid.
- Rubrik validitas bukti dan siapa penilainya.
- Apakah prodi mensyaratkan prototipe aplikasi atau cukup pipeline eksperimen dan artefak replikasi.

## Sumber prior art terdekat

- Zhang dkk., *Prompt-Enhanced Software Vulnerability Detection Using ChatGPT*, https://arxiv.org/abs/2308.12697
- Li dkk., *Everything You Wanted to Know About LLM-based Vulnerability Detection But Were Afraid to Ask*, https://arxiv.org/abs/2504.13474
- Lu dkk., *Evaluating and Enhancing the Vulnerability Reasoning Capabilities of Large Language Models*, https://arxiv.org/html/2602.06687v1
- Xie dkk., *Attribution-Guided Prompt Optimization for Cross-CWE Vulnerability Detection*, https://doi.org/10.3390/info17080762
