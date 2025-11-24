// /api/cron/check-payments.js
import { load_transactions, save_transactions, send_to_telegram } from '../lib/payment-utils';

export default async function handler(request, response) {
  // Secure your cron endpoint with a secret
  if (request.headers.authorization !== `Bearer ${process.env.CRON_SECRET}`) {
    return response.status(401).json({ error: 'Unauthorized' });
  }

  try {
    const transactions = await load_transactions();
    const pendingTxns = transactions.pending || [];
    
    // Check recent pending transactions
    const recentPending = pendingTxns
      .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))
      .slice(0, 10); // Check last 10 transactions

    for (const txn of recentPending) {
      // Your payment checking logic here
      const paymentStatus = await checkPaymentStatus(txn.md5_hash);
      
      if (paymentStatus === 'PAID') {
        // Move to completed and send Telegram
        await processCompletedPayment(txn, transactions);
      }
    }

    await save_transactions(transactions);
    
    response.status(200).json({ 
      success: true, 
      checked: recentPending.length 
    });
  } catch (error) {
    response.status(500).json({ error: error.message });
  }
}

// Add this to your vercel.json configuration
