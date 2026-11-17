# Rencana Pilot & Estimasi Biaya — Prompt Kriteria CWE (v0.1)

**Status:** audit data offline awal **sudah dijalankan**; inferensi LLM dan evaluasi hasil **belum dijalankan**. Dokumen ini kelanjutan `protokol_prompt_cwe_v0.1.md`, bukan hasil penelitian. Anggaran Rp500 ribu–Rp1 juta belum dikonfirmasi sebagai total atau bulanan. Tidak ada API key/billing yang diasumsikan tersedia.

## A. Audit awal dataset yang benar-benar dilakukan

Dataset Task 1 VulDetectBench tersedia pada repo penerbit benchmark sebagai file `dataset/test/task1_code.jsonl`; README menyebut tugas binary vulnerability-existence dan ukuran 1.000 sampel.[2] File publiknya diunduh ke `pilot/data/vuldetectbench_task1_code.jsonl` dan diparsing lokal oleh `pilot/audit_dataset.py` (tanpa mengirim kode ke LLM). SHA-256 file: `af772bb7a6e11cf638941b9b8d53c426c39abc39fcf3410172eed57479da9dd0`.

**Hasil audit aktual:** 1.000 baris; tepat 500 berlabel `YES` dan 500 `NO`; setiap baris punya `answer`, `code`, `cwe`, `idx`; 57 nilai `cwe` berbeda; 1.000 hash kode unik tetapi hanya 967 `idx` unik. Untuk eksperimen *spesifik satu CWE dengan kelas positif dan negatif*, hanya CWE-120 yang muncul di **dua kelas**—1 `YES`, 42 `NO`. Nilai CWE `0` muncul pada 250 sampel `NO`. Distribusi lengkap ada di `pilot/dataset_audit.json`.

**Keputusan sementara: NO-GO** untuk langsung memakai Task 1 ini sebagai dataset utama P1-versus-P2 per-CWE. Total YES/NO global seimbang **tidak** berarti positif-negatif seimbang *pada CWE yang sama*. Nilai `cwe` pada sampel negatif harus ditelusuri semantiknya, bukan diasumsikan label ground truth bahwa kode aman terhadap CWE lain. `idx` tidak unik sehingga tak boleh dipakai sendirian sebagai identifier. Dataset ini berasal dari folder `test`: **jangan dipakai untuk memilih prompt atau mengutak-atik kriteria**, karena akan mencemari evaluasi akhir.

## B. Kandidat data dan gerbang seleksi

**Pilihan utama untuk diaudit berikutnya: PrimeVul-v0.1.** Dokumentasi resminya menyebut fungsi C/C++ nyata, pasangan rentan–patched, pembagian kronologis, dan metadata file/proyek; versi v0.1 tidak memuat metadata CWE untuk setiap sampel.[1] Perlu akses dataset resmi (tautan Drive), lisensi berkas, inspeksi kolom aktual, hitung distribusi positif/negatif *per CWE*, serta periksa split pasangan/proyek sebelum mengklaim layak. Belum diunduh atau dihitung pada tahap ini.

**Cadangan sintetis untuk cek pipeline, bukan generalisasi:** NIST Juliet C/C++ versi 1.3 berisi kasus uji berbagai CWE.[4] Penggunaan contoh good/bad cocok untuk sanity check parser/prompt tetapi dapat berbeda jauh dari kerentanan proyek nyata; periksa lisensi, ukuran unduhan, lokasi label, dan pemisahan varian keluarga kasus. Jangan gabungkan metrik Juliet dan proyek nyata tanpa laporan terpisah.

**Gerbang sebelum inferensi LLM:** pilih satu bahasa dan satu CWE; pastikan ada unit positif dan negatif memadai untuk estimasi yang berguna; definisi label ditelusuri; pasangan dan duplikat dikelompokkan; ada data development **terpisah** dari test; konteks kode cukup; lisensi dan biaya lolos. Bila gagal, ubah dataset/CWE atau pertanyaan penelitian terlebih dulu.

## C. Pilot teknis yang akan dijalankan sesudah data layak

1. Ambil subset *development* berisi kedua label dan lebih dari satu proyek/keluarga; ukuran pilot ditentukan sesudah melihat ketersediaan kelompok independen. **Jangan gunakan file test VulDetectBench yang telah diinspeksi untuk menyetel prompt.**
2. Buat P1 (nama CWE) dan P2 (nama CWE + kriteria/bukti) persis menurut protokol v0.1 dengan **kode identik**; simpan template dan hash-nya.
3. Kunci satu snapshot model, konfigurasi decoding yang didukung, parser JSON, batas konteks, aturan invalid/timeout, urutan seimbang, dan logging token.
4. Jalankan uji sangat kecil untuk validasi respons, bukan untuk mengoptimalkan skor. Catat setiap `sample_id`, `group_id`, label, prediksi, respons mentah, biaya token, waktu, dan kesalahan.
5. Hitung confusion matrix dan audit beberapa perbedaan P1/P2; laporkan apakah bukti merujuk potongan kode nyata. Revisi protokol **hanya** dengan data development. Kemudian bekukan semuanya sebelum test final.
6. Bila model/API tak tersedia, hentikan pada kesiapan data dan estimator biaya; jangan membuat hasil simulasi LLM seolah hasil uji.

**Kriteria GO:** data sepadan P1/P2, parser stabil, kelas positif/negatif valid per target CWE, potensi leakage diperiksa, biaya terukur, dan pembimbing setuju cakupan. **NO-GO:** hanya ada positive sample per CWE, CWE target disimpulkan dari label jawaban, sumber data tidak dapat direproduksi, atau data test dipakai untuk tuning.

## D. Estimasi biaya ilustratif, BUKAN tagihan/penggunaan aktual

Untuk satu kandidat model API, halaman resmi GPT-4.1 Mini menampilkan **$0.40 / 1 juta token input dan $1.60 / 1 juta token output**, dan menyediakan snapshot `gpt-4.1-mini-2025-04-14`.[3] Ini **contoh untuk budgeting**, bukan keputusan bahwa model itu paling akurat, tersedia bagi akun lu, atau sudah dicoba. Tarif, pajak, biaya transaksi, kurs, serta kuota harus dicek lagi saat eksekusi. Jangan mengandalkan cached-input discount atau Batch API tanpa verifikasi syaratnya.

Asumsi *hanya untuk menghitung skenario*: setiap kasus dipanggil dua kali (P1 1.200 token input, P2 1.600 token input; masing-masing 150 token output); kurs kalkulasi **Rp18.000/USD sebagai asumsi pembulatan, bukan kurs live**. Rumus biaya USD per kasus = `(1200+1600)×0.40/1.000.000 + (150+150)×1.60/1.000.000` = **$0.0016**. Hitungan dengan Python sudah diuji:

- **Pilot 20 kasus:** 40 panggilan; $0.032 / Rp576; dengan faktor cadangan 2× menjadi Rp1.152.
- **Studi 200 kasus:** 400 panggilan; $0.32 / Rp5.760; dengan faktor cadangan 2× menjadi Rp11.520.
- **Studi 500 kasus:** 1.000 panggilan; $0.80 / Rp14.400; dengan faktor cadangan 2× menjadi Rp28.800.

**Jangan pakai angka ini sebagai biaya aktual.** Token kode nyata bisa lebih panjang, output reasoning bisa melonjak, pengulangan uji menambah panggilan, dan paket VPS adalah biaya terpisah. Tanpa kepastian kelayakan sampel independen, jumlah 200/500 adalah *skenario*, bukan ukuran sampel final atau jaminan kekuatan statistik. Lihat `pilot/cost_estimator.py` untuk mengubah harga/token/kurs dan menghitung ulang tanpa menebak.

## E. Deliverable tahap ini dan tugas berikut

- **Ada:** data Task 1 VulDetectBench publik, hash file, skrip audit, JSON audit, rencana GO/NO-GO, estimasi skenario berbasis tarif resmi.
- **Belum ada:** pengukuran kemampuan LLM, klaim efektivitas P2, dataset utama tervalidasi, pemilihan CWE final, akses API dan billing.
- **Tugas berikut yang paling penting:** inspeksi PrimeVul-v0.1/alternatif pada tingkat **CWE × label × grup proyek/pasangan**; periksa apakah split development/test dan kode negatif benar-benar memenuhi pertanyaan penelitian.

## Sources

[1] https://raw.githubusercontent.com/DLVulDet/PrimeVul/main/README.md
[2] https://raw.githubusercontent.com/Sweetaroo/VulDetectBench/main/README.md
[3] https://developers.openai.com/api/docs/models/gpt-4.1-mini
[4] https://samate.nist.gov/SARD/test-suites/112
