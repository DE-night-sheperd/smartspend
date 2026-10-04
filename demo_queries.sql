-- =============================================================
--  SmartSpend MySQL: Example CRUD + Report Queries
--  Run with: mysql -S socket -u user -ppass smartspend < demo_queries.sql
-- =============================================================

SELECT '===== 1. INSERT: Sign up a new user via raw SQL =====' AS step;
INSERT INTO core_user
  (user_id, password, email, first_name, last_name, phone, monthly_budget_limit,
   is_staff, is_active, is_superuser, is_guest, login_count, gemini_key_encrypted,
   date_joined, created_at)
VALUES
  (UUID(),
   'pbkdf2_sha256$100000$demo$C+L2kT8G3SjWbN2zQc+R8H4B4P7V1D6N0M2U9K5J8S3A6R4V9B7N3Q=',
   'john@example.com', 'John', 'Doe', '+27831112233', 10000.00,
   0, 1, 0, 0, 0, '',
   NOW(), NOW())
ON DUPLICATE KEY UPDATE first_name = VALUES(first_name);
SELECT email, first_name, last_name, monthly_budget_limit FROM core_user WHERE email='john@example.com';

SELECT '===== 2. UPDATE: Change John''s budget + phone =====' AS step;
UPDATE core_user
   SET monthly_budget_limit = 15000.00,
       phone                = '+27839998877'
 WHERE email = 'john@example.com';
SELECT email, monthly_budget_limit, phone FROM core_user WHERE email='john@example.com';

SELECT '===== 3. INSERT: Store, Receipt, 3 line items for John =====' AS step;
INSERT IGNORE INTO core_store (store_name, channel_type, created_at)
  VALUES ('Woolworths', 'Physical_Store', NOW());
SET @store_id  = (SELECT store_id  FROM core_store WHERE store_name = 'Woolworths' LIMIT 1);
SET @user_uuid = (SELECT user_id  FROM core_user  WHERE email     = 'john@example.com' LIMIT 1);

INSERT INTO core_receipt
  (user_id, store_id, purchase_date, total_amount, source_type,
   branch_name, cashier_name, slip_number, payment_method, verified,
   original_text, created_at)
VALUES
  (@user_uuid, @store_id, CURDATE(), 342.75, 'camera',
   'Woolworths Sandton', 'M. Smith', 'SLIP-99887', 'Mastercard ••9999', 1,
   'Woolworths Sandton - Demo Receipt\nFree Range Eggs 12pk R38.99\nGreek Yogurt 1kg x2 R54.50\nLuxury Chocolate Box R149.99\nTOTAL R342.75',
   NOW());
SET @receipt_id = LAST_INSERT_ID();

INSERT INTO core_receiptitem (receipt_id, category_id, item_name, unit_price, quantity, is_impulse)
  SELECT @receipt_id, category_id, 'Free Range Eggs 12pk', 38.99, 1, 0
  FROM core_category WHERE category_name = 'Groceries';
INSERT INTO core_receiptitem (receipt_id, category_id, item_name, unit_price, quantity, is_impulse)
  SELECT @receipt_id, category_id, 'Greek Yogurt 1kg', 54.50, 2, 0
  FROM core_category WHERE category_name = 'Groceries';
INSERT INTO core_receiptitem (receipt_id, category_id, item_name, unit_price, quantity, is_impulse)
  SELECT @receipt_id, category_id, 'Luxury Chocolate Box', 149.99, 1, 1
  FROM core_category WHERE category_name = 'Snacks & Drinks';
SELECT CONCAT('Receipt ', @receipt_id, ' created with ', (SELECT COUNT(*) FROM core_receiptitem WHERE receipt_id=@receipt_id), ' items') AS result;

SELECT '===== 4. INSERT: Loyalty points (WRewards) + Budget alert =====' AS step;
INSERT INTO core_loyaltypoints
  (user_id, store_id, receipt_id, points, label, expires_at, created_at)
VALUES
  (@user_uuid, @store_id, @receipt_id, 850, 'Woolworths WRewards',
   DATE_ADD(CURDATE(), INTERVAL 60 DAY), NOW());

INSERT INTO core_budgetalert (user_id, kind, period, sent_at, detail)
VALUES (@user_uuid, 'budget_50', DATE_FORMAT(CURDATE(), '%Y-%m'), NOW(),
        'R342.75 of R15000 monthly budget used so far');
SELECT 'Inserted loyalty record and budget dedup alert entry' AS result;

SELECT '===== 5. REPORT: Spending by category (JOIN + GROUP BY) =====' AS step;
SELECT c.category_name,
       COUNT(ri.item_id)                         AS items,
       FORMAT(SUM(ri.unit_price * ri.quantity),2) AS total_R,
       SUM(CASE WHEN ri.is_impulse THEN 1 ELSE 0 END) AS impulse_items
FROM core_receipt r
JOIN core_receiptitem ri ON ri.receipt_id = r.receipt_id
JOIN core_category c      ON c.category_id   = ri.category_id
WHERE r.user_id = @user_uuid
GROUP BY c.category_name
ORDER BY SUM(ri.unit_price * ri.quantity) DESC;

SELECT '===== 6. REPORT: User overview (all registered users) =====' AS step;
SELECT
  u.email,
  CONCAT(u.first_name, ' ', u.last_name)        AS full_name,
  CONCAT('R', FORMAT(u.monthly_budget_limit,2)) AS monthly_budget,
  COUNT(DISTINCT r.receipt_id)                  AS total_receipts,
  CONCAT('R', FORMAT(COALESCE(SUM(DISTINCT r.total_amount),0),2)) AS lifetime_spent,
  COALESCE(SUM(DISTINCT lp.points), 0)          AS loyalty_points
FROM core_user u
LEFT JOIN core_receipt        r  ON r.user_id  = u.user_id
LEFT JOIN core_loyaltypoints  lp ON lp.user_id = u.user_id
GROUP BY u.user_id
ORDER BY COALESCE(SUM(DISTINCT r.total_amount),0) DESC;

SELECT '===== 7. DELETE: Remove John''s chocolate impulse item =====' AS step;
DELETE ri
FROM core_receiptitem ri
JOIN core_receipt r ON r.receipt_id = ri.receipt_id
WHERE r.user_id = @user_uuid AND ri.is_impulse = 1;
SELECT ROW_COUNT() AS rows_deleted;

SELECT '===== 8. UPDATE: Bulk price increase on John''s groceries (+10%) =====' AS step;
UPDATE core_receiptitem ri
JOIN core_receipt  r ON r.receipt_id = ri.receipt_id
JOIN core_category c ON c.category_id = ri.category_id
   SET ri.unit_price = ROUND(ri.unit_price * 1.10, 2)
 WHERE r.user_id = @user_uuid AND c.category_name = 'Groceries';
SELECT ROW_COUNT() AS items_updated_10pct;

SELECT '===== 9. FINAL: John''s receipt after edits =====' AS step;
SELECT
  r.slip_number,
  r.purchase_date,
  r.branch_name,
  ri.item_name,
  c.category_name,
  CONCAT('R', FORMAT(ri.unit_price,2)) AS price,
  ri.quantity,
  CONCAT('R', FORMAT(ri.unit_price * ri.quantity, 2)) AS line_total,
  ri.is_impulse
FROM core_receipt r
JOIN core_receiptitem ri ON ri.receipt_id = r.receipt_id
JOIN core_category c     ON c.category_id   = ri.category_id
WHERE r.user_id = @user_uuid;
