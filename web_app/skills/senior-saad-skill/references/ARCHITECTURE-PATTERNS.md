# 🏗️ SAAD Architecture Patterns Reference
## Senior SAAD System — Common Architecture Patterns

---

## PATTERN 1: SaaS Web Application

```
Frontend (Next.js App Router)
├── Landing Page (/ ) — public
├── Auth (/auth/login, /auth/signup)
├── Dashboard (/dashboard) — protected
├── Feature Pages (/[feature])
└── Settings (/settings)

Backend (Next.js API Routes / Separate Node.js)
├── /api/auth/* — Auth endpoints
├── /api/users/* — User management
├── /api/[resource]/* — Core business logic
└── /api/webhooks/* — External service webhooks

Database Layer
├── PostgreSQL — relational data
├── Redis — sessions, cache, rate limiting
└── S3/Cloudinary — file storage

External Services
├── Auth: Clerk / Auth.js / Supabase Auth
├── Email: Resend / SendGrid
├── Payments: Stripe
└── Monitoring: Sentry + Posthog
```

---

## PATTERN 2: Real-Time Application (Chat / Collaboration)

```
Frontend + WebSocket Client
├── React with Zustand (local state)
├── Socket.io client (real-time)
└── Optimistic UI updates

Backend
├── Node.js + Express/Fastify
├── Socket.io server
└── Bull Queue (background jobs)

Data
├── PostgreSQL — persistent data
├── Redis — pub/sub, presence, real-time state
└── CDN — media files
```

---

## PATTERN 3: IoT / Dashboard System

```
Devices → MQTT Broker → Processing → Database → API → Dashboard
                                   ↓
                             InfluxDB (time-series)
                             PostgreSQL (metadata)
                             Redis (real-time cache)

Dashboard
├── React + Recharts/D3 (visualization)
├── WebSocket (live updates)
└── REST API (historical data)
```

---

## COMMON DATABASE PATTERNS

### User Account Pattern
```sql
users
  id UUID PRIMARY KEY
  email VARCHAR UNIQUE NOT NULL
  password_hash VARCHAR
  role ENUM('admin','user','moderator')
  created_at TIMESTAMP DEFAULT NOW()
  updated_at TIMESTAMP

profiles
  id UUID PRIMARY KEY
  user_id UUID REFERENCES users(id)
  display_name VARCHAR
  avatar_url VARCHAR
  bio TEXT
```

### Audit Trail Pattern
```sql
audit_logs
  id UUID PRIMARY KEY
  user_id UUID REFERENCES users(id)
  action VARCHAR NOT NULL  -- 'CREATE', 'UPDATE', 'DELETE'
  entity_type VARCHAR      -- 'post', 'order', etc.
  entity_id UUID
  old_values JSONB
  new_values JSONB
  ip_address INET
  created_at TIMESTAMP DEFAULT NOW()
```

### Soft Delete Pattern
```sql
-- Add to any table that needs soft delete
deleted_at TIMESTAMP DEFAULT NULL
-- Query: WHERE deleted_at IS NULL
```

---

## SECURITY PATTERNS

### JWT Auth Flow
```
1. User submits credentials
2. Server validates → generates access_token (15min) + refresh_token (7days)
3. Client stores: access_token in memory, refresh_token in httpOnly cookie
4. Every request: Authorization: Bearer [access_token]
5. On 401: automatically refresh via /api/auth/refresh
6. On logout: revoke refresh_token in DB
```

### Rate Limiting Strategy
```
Public endpoints:    100 req/min per IP
Auth endpoints:      5 req/min per IP (strict)
Authenticated API:   1000 req/min per user
File uploads:        10 req/min per user
```

---

*SAAD Architecture Patterns v2.0 — Senior SAAD System*
