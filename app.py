from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlmodel import SQLModel, Field, Session, create_engine, select
import os, secrets, datetime as dt

PUBLIC_APP_BASE = os.getenv("PUBLIC_APP_BASE", "http://localhost:8000")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")

engine = create_engine(DATABASE_URL, echo=False)
app = FastAPI(title="Anon Affiliate Backend – Step2", version="0.2")

class AffiliateItem(SQLModel, table=True):
    id: str = Field(primary_key=True)
    title: str
    image: str | None = None
    price: float | None = None
    category: str | None = None
    partner: str | None = None
    tracking_url: str | None = None
    city: str | None = None

class Offer(SQLModel, table=True):
    id: str = Field(primary_key=True, default_factory=lambda: secrets.token_hex(8))
    giver_id: str
    item_id: str
    message: str
    city: str | None = None
    expires_at: dt.datetime
    status: str = "sent"
    subid: str = Field(default_factory=lambda: secrets.token_hex(6))

class Interest(SQLModel, table=True):
    id: str = Field(primary_key=True, default_factory=lambda: secrets.token_hex(8))
    offer_id: str
    receiver_id: str
    created_at: dt.datetime = Field(default_factory=lambda: dt.datetime.utcnow())

class Consent(SQLModel, table=True):
    offer_id: str = Field(primary_key=True)
    giver_ok: bool = False
    receiver_ok: bool = False
    at: dt.datetime | None = None

class OfferCreate(BaseModel):
    giver_id: str
    item_id: str
    message: str
    city: str | None = None
    expires_at: dt.datetime

class FeedQuery(BaseModel):
    receiver_id: str
    city: str | None = None

def get_session():
    with Session(engine) as session:
        yield session

@app.on_event("startup")
def on_startup():
    SQLModel.metadata.create_all(engine)

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/sync")
def sync_catalog(session: Session = Depends(get_session)):
    sample = [
        {"id": "food-1", "title": "Degustačné menu pre dvoch", "price": 59.0, "category": "food", "partner": "TheFork", "tracking_url": "https://partner.example/offer?aid=APP123", "city":"Bratislava"},
        {"id": "hotel-1", "title": "Víkend v Hoteli Riviera", "price": 220.0, "category": "hotel", "partner": "Booking", "tracking_url": "https://partner.example/hotel?aid=APP123", "city":"Bratislava"},
        {"id": "exp-1", "title": "Plavba pri západe slnka", "price": 39.0, "category": "experience", "partner": "GetYourGuide", "tracking_url": "https://partner.example/exp?aid=APP123", "city":"Zadar"},
    ]
    for it in sample:
        if not session.get(AffiliateItem, it["id"]):
            session.add(AffiliateItem(**it))
    session.commit()
    return {"synced": len(sample)}

@app.get("/catalog")
def catalog(city: str | None = None, category: str | None = None, session: Session = Depends(get_session)):
    stmt = select(AffiliateItem)
    if city:
        stmt = stmt.where(AffiliateItem.city == city)
    if category:
        stmt = stmt.where(AffiliateItem.category == category)
    return session.exec(stmt).all()

@app.post("/offers", response_model=Offer)
def create_offer(body: OfferCreate, session: Session = Depends(get_session)):
    item = session.get(AffiliateItem, body.item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    offer = Offer(
        giver_id=body.giver_id,
        item_id=body.item_id,
        message=body.message,
        city=body.city or item.city,
        expires_at=body.expires_at,
        status="sent",
    )
    session.add(offer); session.commit(); session.refresh(offer)
    session.add(Consent(offer_id=offer.id)); session.commit()
    return offer

@app.get("/offers/{offer_id}", response_model=Offer)
def get_offer(offer_id: str, session: Session = Depends(get_session)):
    offer = session.get(Offer, offer_id)
    if not offer: raise HTTPException(404, "Offer not found")
    return offer

@app.post("/offers/{offer_id}/interest")
def interest(offer_id: str, receiver_id: str, session: Session = Depends(get_session)):
    offer = session.get(Offer, offer_id)
    if not offer: raise HTTPException(404, "Offer not found")
    if offer.expires_at < dt.datetime.utcnow():
        raise HTTPException(410, "Offer expired")
    session.add(Interest(offer_id=offer_id, receiver_id=receiver_id))
    offer.status = "interested"
    session.add(offer); session.commit()
    return {"ok": True}

@app.post("/offers/{offer_id}/consent/giver")
def consent_giver(offer_id: str, ok: bool, session: Session = Depends(get_session)):
    c = session.get(Consent, offer_id)
    if not c: raise HTTPException(404, "Consent missing")
    c.giver_ok = ok
    _update_consent_state(offer_id, c, session)
    return {"ok": True}

@app.post("/offers/{offer_id}/consent/receiver")
def consent_receiver(offer_id: str, ok: bool, session: Session = Depends(get_session)):
    c = session.get(Consent, offer_id)
    if not c: raise HTTPException(404, "Consent missing")
    c.receiver_ok = ok
    _update_consent_state(offer_id, c, session)
    return {"ok": True}

def _update_consent_state(offer_id: str, c: Consent, session: Session):
    if c.giver_ok and c.receiver_ok:
        c.at = dt.datetime.utcnow()
        offer = session.get(Offer, offer_id)
        offer.status = "consented"
        session.add(offer)
    session.add(c); session.commit()

@app.post("/offers/{offer_id}/claim-link")
def claim_link(offer_id: str, session: Session = Depends(get_session)):
    offer = session.get(Offer, offer_id)
    if not offer: raise HTTPException(404, "Offer not found")
    return {"claim_url": f"{PUBLIC_APP_BASE}/c/{offer.subid}", "subid": offer.subid}

@app.get("/c/{subid}")
def handle_claim(subid: str, session: Session = Depends(get_session)):
    offer = session.exec(select(Offer).where(Offer.subid == subid)).first()
    if not offer: raise HTTPException(404, "Invalid token")
    if offer.expires_at < dt.datetime.utcnow():
        raise HTTPException(410, "Offer expired")
    item = session.get(AffiliateItem, offer.item_id)
    if not item or not item.tracking_url:
        raise HTTPException(404, "Item unavailable")
    sep = "&" if "?" in item.tracking_url else "?"
    target = f"{item.tracking_url}{sep}subid={offer.subid}"
    return RedirectResponse(url=target)

@app.post("/feed")
def feed(q: FeedQuery, session: Session = Depends(get_session)):
    stmt = select(Offer).where(Offer.status.in_(["sent","interested"]))
    if q.city:
        stmt = stmt.where(Offer.city == q.city)
    offers = session.exec(stmt).all()
    out = []
    for of in offers:
        item = session.get(AffiliateItem, of.item_id)
        out.append({"offer": of, "item": item})
    return out
