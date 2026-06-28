import { apiFetch } from '../composables/useWebSocket'

export function listBrands() {
  return apiFetch('/brands')
}

export function createBrand({ brand_id, brand_name, company_name, website, industry }) {
  return apiFetch('/brands', {
    method: 'POST',
    body: JSON.stringify({ brand_id, brand_name, company_name, website, industry }),
  })
}

export function updateBrand(brandId, { brand_name, company_name, website, industry }) {
  return apiFetch(`/brands/${brandId}`, {
    method: 'PUT',
    body: JSON.stringify({ brand_name, company_name, website, industry }),
  })
}

export function deleteBrand(brandId) {
  return apiFetch(`/brands/${brandId}`, { method: 'DELETE' })
}

export function getCurrentBrand() {
  return apiFetch('/brands/current')
}

export function setCurrentBrand(brandId) {
  return apiFetch('/brands/current', {
    method: 'PUT',
    body: JSON.stringify({ brand_id: brandId }),
  })
}
