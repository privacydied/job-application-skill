# HMCTS SBA (2004059) — finish via VNC (2 min)

Automation is BLOCKED on the General Information step: the Country/`<select>` fields get
NO browser ref and camofox `evaluate` cannot address the heavy native select node.
Everything else is built. Account already created.

## Login
- URL: https://jobs.justice.gov.uk/careers/JobDetail/19623
- Email: you@example.com  (MoJ row in ats-credentials.csv)
- You are already registered; just sign in.

## Step path (resume at General Information, step 4 of 7)
1. Account detail — done.
2. Eligibility — done (passed).
3. General Information — COMPLETE THIS:
   - Title: Mr.
   - First/Last/Preferred: Jane / Doe / Jane
   - NI number: No
   - Country: **United Kingdom**  ← the blocked field; pick from dropdown
   - County: Greater London
   - First line: [your address]
   - Town/City: London
   - Postcode: [postcode]
   - Personal email: you@example.com
   - UK mobile: Yes → number 07700900000
   - Text consent: Yes
   - Current employment: Non Civil Servant
   - Organisation: AGY - HMCTS
   - Directly employed: I Confirm
   - Applying for a.../intention to continue: No / No
   - Veteran/redeploy/surplus/promotion/fixed-term/discipline: all No
   - Nationality req met: Yes ; right to work: Yes
   - English first/dominant: Yes / Yes
   - Other nationalities / immigration controls: No / No
   - Nationality details: British
   - Click **Save and Continue**
4. Success Profile — BA behaviours (free text):
   - Communicating and Influencing
   - Working Together
   - Making Effective Decisions
   - Changing and Improving
   (reuse applications/cabinet-office-user-researcher/personal-statement.txt)
5. Equality & Diversity — applicant defaults: [your ethnicity] / [your gender] / [your orientation] /
   [your national identity] / [your age band] / [your disability status] / [your carer status].
6. Declaration — confirm.
7. Submit.

## On submit: tell the agent the ref, or paste "Application received" — it will
verify and mark the tracker row Applied (currently Blocked).
