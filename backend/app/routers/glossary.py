"""Glosario jopara/guaraní: correcciones human-in-the-loop."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Company, GlossaryTerm

router = APIRouter(tags=["glossary"])


class TermIn(BaseModel):
    heard: str = Field(min_length=1, max_length=200)
    corrected: str = Field(min_length=1, max_length=200)
    meaning: str = ""


class TermOut(TermIn):
    id: int

    model_config = {"from_attributes": True}


@router.post("/companies/{company_id}/glossary", response_model=TermOut, status_code=201)
def create_term(company_id: int, payload: TermIn, db: Session = Depends(get_db)):
    if not db.get(Company, company_id):
        raise HTTPException(404, "Empresa no encontrada")
    exists = (
        db.query(GlossaryTerm)
        .filter(GlossaryTerm.company_id == company_id, GlossaryTerm.heard == payload.heard)
        .first()
    )
    if exists:
        raise HTTPException(409, "Ya existe una corrección para ese término")
    term = GlossaryTerm(company_id=company_id, **payload.model_dump())
    db.add(term)
    db.commit()
    db.refresh(term)
    return term


@router.get("/companies/{company_id}/glossary", response_model=list[TermOut])
def list_terms(company_id: int, db: Session = Depends(get_db)):
    if not db.get(Company, company_id):
        raise HTTPException(404, "Empresa no encontrada")
    return db.query(GlossaryTerm).filter(GlossaryTerm.company_id == company_id).order_by(GlossaryTerm.id).all()


@router.delete("/companies/{company_id}/glossary/{term_id}", status_code=204)
def delete_term(company_id: int, term_id: int, db: Session = Depends(get_db)):
    term = db.get(GlossaryTerm, term_id)
    if not term or term.company_id != company_id:
        raise HTTPException(404, "Término no encontrado")
    db.delete(term)
    db.commit()
