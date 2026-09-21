export interface Account {
  id: string
  username: string
  display_name: string | null
  role: 'admin' | 'teacher'
  is_active: boolean
  version: number
}

export interface Me {
  account: Account
  class_id: null
  assignment_status: string
  can_prepare: boolean
}

export interface ErrorBody {
  error: {
    code: string
    message: string
    fields?: Record<string, string>
  }
}
