import admin from 'firebase-admin';
import { createRequire } from 'module';

const require = createRequire(import.meta.url);
const serviceAccount = require('../Keys/r01-redditx-suicide-firebase-adminsdk-fbsvc-306bc4ee85.json');

admin.initializeApp({
  credential: admin.credential.cert(serviceAccount),
});

const db = admin.firestore();

async function checkTest2() {
  console.log('Checking test2 data in Firebase...\n');
  console.log('Path: participants/test2/events/\n');

  // Check events subcollection for test2
  const eventsSnapshot = await db.collection('participants')
    .doc('test2')
    .collection('events')
    .limit(30)
    .get();

  console.log(`=== Events for test2: ${eventsSnapshot.size} ===\n`);

  const typeCounts = {};
  let screenshotsWithOcr = 0;
  let totalOcrWords = 0;

  eventsSnapshot.forEach((doc) => {
    const data = doc.data();
    typeCounts[data.eventType] = (typeCounts[data.eventType] || 0) + 1;

    if (data.eventType === 'screenshot') {
      const hasOcr = data.ocr && data.ocr.wordCount > 0;
      if (hasOcr) screenshotsWithOcr++;
      totalOcrWords += data.ocr?.wordCount || 0;

      console.log(`Screenshot: ${doc.id}`);
      console.log(`  Timestamp: ${data.timestamp?.toDate?.() || 'n/a'}`);
      console.log(`  Storage URL: ${data.screenshotUrl ? 'yes' : 'no'}`);
      if (data.ocr) {
        console.log(`  OCR Words: ${data.ocr.wordCount}`);
        console.log(`  OCR Time: ${data.ocr.processingTimeMs}ms`);
        console.log(`  OCR Text: "${(data.ocr.extractedText || '').substring(0, 200)}"`);
      } else {
        console.log(`  OCR: (none)`);
      }
      console.log('---');
    }
  });

  console.log('\n=== Summary ===');
  console.log('Event types:', typeCounts);
  console.log(`Screenshots with OCR text: ${screenshotsWithOcr}`);
  console.log(`Total OCR words: ${totalOcrWords}`);

  // Also check test1 for comparison
  console.log('\n\n=== Also checking test1 ===');
  const test1Events = await db.collection('participants')
    .doc('test1')
    .collection('events')
    .limit(5)
    .get();
  console.log(`test1 events: ${test1Events.size}`);

  process.exit(0);
}

checkTest2().catch(console.error);
