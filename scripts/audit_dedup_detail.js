// Dump full records for the specific events in Achilles' audit deck.
import admin from 'firebase-admin';
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const serviceAccount = require('../Keys/r01-redditx-suicide-firebase-adminsdk-fbsvc-306bc4ee85.json');
admin.initializeApp({ credential: admin.credential.cert(serviceAccount) });
const db = admin.firestore();
const PREFIX = process.env.ENVIRONMENT === 'dev' ? 'dev_' : '';

const IDS = [
  '6cbab637-5d2e-450a-96e9-80d60a107de4',
  'e1746956-2da0-4479-a950-bb142e651da0',
  'b91a5482-04bd-422b-a770-a17d2012caa4',
  'e42fc5c4-6966-4ce0-a40f-4ab5a1f703f8',
  'ca39e47c-18d5-4461-9ad4-8d0dfa42de86',
  '15937e1b-8d58-41f4-b6c1-d955f8e67770',
  'd458f537-2c56-4131-acac-a7242a4a74c0',
];
const parse = (d) => { if (!d) return {}; if (typeof d === 'object') return d; try { return JSON.parse(d); } catch { return {}; } };

const run = async () => {
  const parts = await db.collection(`${PREFIX}participants`).get();
  for (const p of parts.docs) {
    for (const id of IDS) {
      const d = await p.ref.collection('events').doc(id).get();
      if (!d.exists) continue;
      const v = d.data();
      const data = parse(v.data);
      console.log(`\n=== ${id} (participant ${p.id}) ===`);
      console.log('  type:', v.eventType, '| session:', v.sessionId, '| ts:', v.timestamp?.toDate?.()?.toISOString?.() || v.timestamp);
      console.log('  dedup:', data.dedup, '| dedupOfEventId:', data.dedupOfEventId);
      console.log('  contentHash:', data.contentHash);
      console.log('  filePath:', (data.filePath || '').split('/').pop());
      console.log('  screenshotUrl:', v.screenshotUrl || '(none)');
      // any children of this event?
      for (const sub of ['screenshots', 'ocr_results']) {
        const c = await d.ref.collection(sub).limit(5).get().catch(() => null);
        if (c && !c.empty) console.log(`  ${sub}:`, c.docs.map((x) => x.id).join(', '));
      }
    }
    // Do any of the IDS exist as docs in other subcollections (e.g. ocr_results keyed by image id)?
    for (const sub of ['ocr_results', 'screenshots']) {
      for (const id of IDS) {
        const d = await p.ref.collection(sub).doc(id).get().catch(() => null);
        if (d && d.exists) console.log(`\n[${sub}] ${id} exists for ${p.id}:`, JSON.stringify(d.data()).slice(0, 300));
      }
    }
  }
  process.exit(0);
};
run().catch((e) => { console.error(e); process.exit(1); });
