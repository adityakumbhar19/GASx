CREATE TABLE IF NOT EXISTS employees (
    id          SERIAL PRIMARY KEY,
    emp_code    VARCHAR(20) UNIQUE NOT NULL,
    full_name   VARCHAR(100) NOT NULL,
    department  VARCHAR(50),
    is_active   BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS nfc_cards (
    id          SERIAL PRIMARY KEY,
    card_uid    VARCHAR(32) UNIQUE NOT NULL,
    employee_id INT NOT NULL REFERENCES employees(id),
    is_active   BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS attendance_logs (
    id          BIGSERIAL PRIMARY KEY,
    employee_id INT NOT NULL REFERENCES employees(id),
    direction   VARCHAR(3) NOT NULL CHECK (direction IN ('IN', 'OUT')),
    tapped_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_logs_emp_time
    ON attendance_logs (employee_id, tapped_at DESC);

CREATE TABLE IF NOT EXISTS employee_photos (
    employee_id INT PRIMARY KEY REFERENCES employees(id) ON DELETE CASCADE,
    photo       BYTEA NOT NULL,
    mime_type   VARCHAR(30) NOT NULL DEFAULT 'image/jpeg',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);