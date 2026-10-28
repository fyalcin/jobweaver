import { createContext, useContext } from 'react'

export const ApiContext = createContext(null)

export function useApi() {
  const api = useContext(ApiContext)
  if (!api) throw new Error('Authenticated workflows require a user workspace')
  return api
}
