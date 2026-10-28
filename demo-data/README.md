# Demo upload files (Mumbai)

These files are CSVs. They open in Excel, but save them as **CSV**, not .xlsx: the uploader only takes CSV.

## Before uploading
Replace `REPLACE_WITH_YOUR_MOBILE` in `reps.csv` and `doctors.csv` with your own 10-digit mobile number:

```bash
sed -i '' 's/REPLACE_WITH_YOUR_MOBILE/<your 10 digits>/' reps.csv doctors.csv
```

The other reps have dummy numbers (`0000000001`–`0000000003`). Never press "Call now" on them.

## Upload order (Setup → 1. Your data)
1. `reps.csv`: 4 reps. You cover Andheri, Bandra and Powai.
2. `products.csv`: 20 products, including the ones that are often misheard (Azithral 500, Montair LC, Cardivas 6.25, Telma H).
3. `doctors.csv`: 12 doctors. 6 are assigned to you. Upload this after reps, because `rep_phone` links each doctor to a rep.
4. `chemists.csv`: 8 chemists.

`reps_with_errors.csv` lets you see the validation. It should flag a duplicate phone number, a missing phone number and a bad number, and keep 1 row.

Then click **Create voice agent**.

## Things to say on a test call
- **Debrief:** "Dr Sharma se mil ke aaya, Andheri mein. Telma 40 aur Azithral 500 discuss kiya, Telma ke 4 strip sample diye. Krishna Medical pe Montair LC ka order 30, Pan D stock mein nahi hai. Unhone clinical study maangi, Friday ko follow up karna hai." ("Just met Dr Sharma, in Andheri. Discussed Telma 40 and Azithral 500, gave him 4 sample strips of Telma. Order of 30 Montair LC at Krishna Medical, Pan D is out of stock. He asked for the clinical study, I have to follow up on Friday.")
- **Briefing (after the debrief):** "Dr Sharma se milne ja raha hoon." ("I'm on my way to meet Dr Sharma.")
- **To test name checking, mumble a name:** "Exezle 500", "char divas", "monter".
