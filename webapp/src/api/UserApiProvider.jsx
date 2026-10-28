import React, { useEffect, useState } from 'react'
import { ApiContext } from './context'
import { createAuthenticatedClient } from './client'

export function UserApiProvider({ children }) {
  const [client] = useState(createAuthenticatedClient)
  useEffect(() => {
    client.activate()
    return () => client.dispose()
  }, [client])
  return <ApiContext.Provider value={client.api}>{children}</ApiContext.Provider>
}
